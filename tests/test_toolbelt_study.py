"""Validate test-call attribution and ordered toolbelt comparisons."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from benchmarks.toolbelt_study import (combine, graphify_ranked_paths, oracle_by_source_test,
                                       paired_hit_interval)

PROJECT = Path(__file__).resolve().parents[1]


class ToolbeltStudyTests(unittest.TestCase):
    def test_graphify_prefers_extracted_calls_over_shorter_inferred_path(self):
        nodes = [
            {"id": "src_pkg_core_target", "source_file": "src/pkg/core.py",
             "label": "target()", "_callable": True},
            {"id": "tests_test_core_test_a", "source_file": "tests/test_core.py",
             "label": "test_a()", "_callable": True},
            {"id": "tests_test_core_test_b", "source_file": "tests/test_core.py",
             "label": "test_b()", "_callable": True},
        ]
        graph = {"nodes": nodes, "edges": [
            {"source": "tests_test_core_test_a", "target": "helper", "relation": "calls",
             "confidence": "EXTRACTED"},
            {"source": "helper", "target": "src_pkg_core_target", "relation": "calls",
             "confidence": "EXTRACTED"},
            {"source": "tests_test_core_test_b", "target": "src_pkg_core_target",
             "relation": "indirect_call", "confidence": "INFERRED"},
            {"source": "tests_test_core_test_b", "target": "src_pkg_core_target",
             "relation": "imports", "confidence": "EXTRACTED"},
        ]}
        ranked, coverage = graphify_ranked_paths(graph, "src/pkg/core.py::target",
                                                  ["tests/test_core.py::test_a",
                                                   "tests/test_core.py::test_b"])
        self.assertEqual([row["test"] for row in ranked],
                         ["tests/test_core.py::test_a", "tests/test_core.py::test_b"])
        self.assertEqual([row["inferred_edges"] for row in ranked], [0, 1])
        self.assertTrue(coverage["function_mapped"])
        self.assertEqual(coverage["tests_mapped"], 2)

    def test_toolbelt_inserts_jev_before_shared_lexical_fallback(self):
        result = combine(("graphify", ["a"]), ("jev", ["c", "a"]),
                         ("lexical", ["b", "c", "d"]))
        self.assertEqual(result, [{"test": "a", "source": "graphify"},
                                  {"test": "c", "source": "jev"},
                                  {"test": "b", "source": "lexical"}])

    def test_full_suite_plugin_attributes_calls_to_each_test(self):
        root = PROJECT / "examples/mini_repo"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "calls.json"
            environment = dict(os.environ)
            environment.update(JEV_MAP_PROFILE_ROOT=str(root), JEV_MAP_PROFILE_OUTPUT=str(output))
            environment["PYTHONPATH"] = os.pathsep.join((str(PROJECT / "benchmarks"), str(root)))
            result = subprocess.run([sys.executable, "-m", "pytest", "-q",
                                     "test_text_ops.py", "-p", "full_suite_profile"],
                                    cwd=root, env=environment, capture_output=True,
                                    text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            raw = json.loads(output.read_text())
        tests = [f"test_text_ops.py::TextTests.{name}" for name in
                 ("test_normalize", "test_slugify", "test_port", "test_port_invalid", "test_compact")]
        aggregate, stats = oracle_by_source_test(raw, tests)
        self.assertEqual(stats["eligible"], 5)
        self.assertIn("text_ops.py::normalize", aggregate[tests[0]]["observed"])
        self.assertNotIn("text_ops.py::slugify", aggregate[tests[0]]["observed"])
        self.assertIn("text_ops.py::slugify", aggregate[tests[1]]["observed"])

    def test_full_suite_plugin_marks_surviving_workers_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "target.py").write_text(
                "def worker_only():\n    return 1\n\n"
                "def runner_only():\n    return 2\n")
            (root / "test_threads.py").write_text(
                "from threading import Event, Thread\n"
                "from target import worker_only, runner_only\n"
                "go = Event()\nworker = None\n\n"
                "def run_worker():\n    go.wait()\n    worker_only()\n\n"
                "def test_start_worker():\n"
                "    global worker\n"
                "    worker = Thread(target=run_worker)\n"
                "    worker.start()\n\n"
                "def test_release_worker():\n"
                "    go.set()\n"
                "    worker.join(timeout=2)\n"
                "    assert not worker.is_alive()\n"
                "    assert runner_only() == 2\n\n"
                "def test_joined_worker():\n"
                "    joined = Thread(target=worker_only)\n"
                "    joined.start()\n"
                "    joined.join(timeout=2)\n"
                "    assert not joined.is_alive()\n")
            output = root / "calls.json"
            environment = dict(os.environ)
            environment.update(JEV_MAP_PROFILE_ROOT=str(root), JEV_MAP_PROFILE_OUTPUT=str(output))
            environment["PYTHONPATH"] = os.pathsep.join((str(PROJECT / "benchmarks"), str(root)))
            result = subprocess.run([sys.executable, "-m", "pytest", "-q",
                                     "test_threads.py", "-p", "full_suite_profile"],
                                    cwd=root, env=environment, capture_output=True,
                                    text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            cases = json.loads(output.read_text())["cases"]
        for name in ("test_start_worker", "test_release_worker"):
            self.assertNotIn("target.py::worker_only", cases[f"test_threads.py::{name}"]["observed"])
        self.assertNotIn("target.py::runner_only", cases["test_threads.py::test_start_worker"]["observed"])
        self.assertIn("target.py::runner_only", cases["test_threads.py::test_release_worker"]["observed"])
        self.assertIn("target.py::worker_only", cases["test_threads.py::test_joined_worker"]["observed"])
        aggregate, stats = oracle_by_source_test(raw={"cases": cases}, test_ids=list(cases))
        self.assertEqual(stats["threaded"], 2)
        self.assertEqual(stats["thread_coverage_unknown"], 2)
        for name in ("test_start_worker", "test_release_worker"):
            row = aggregate[f"test_threads.py::{name}"]
            self.assertEqual(row["reason"], "thread_coverage_unknown")
            self.assertFalse(row["eligible"])
        self.assertTrue(aggregate["test_threads.py::test_joined_worker"]["eligible"])

    def test_paired_interval_preserves_function_clustering(self):
        rows = [{"repository": name, "observed_tests": ["test"],
                 "methods": {"base": [{"observed": False}],
                             "improved": [{"observed": True}]}}
                for name in ("a", "a", "b", "b")]
        interval = paired_hit_interval(rows, {"bootstrap_seed": "fixed",
                                              "bootstrap_resamples": 100}, "base", "improved")
        self.assertEqual(interval["lower_95"], 1)
        self.assertEqual(interval["upper_95"], 1)

    def test_skipped_parameter_variant_is_unknown_not_negative(self):
        raw = {"cases": {
            "tests/test_a.py::test_a[one]": {"observed": ["src/a.py::run"],
                "reports": [{"when": "call", "outcome": "passed"}]},
            "tests/test_a.py::test_a[two]": {"observed": [],
                "reports": [{"when": "call", "outcome": "skipped"}]},
        }}
        aggregate, stats = oracle_by_source_test(raw, ["tests/test_a.py::test_a"])
        self.assertFalse(aggregate["tests/test_a.py::test_a"]["eligible"])
        self.assertEqual(aggregate["tests/test_a.py::test_a"]["observed"], [])
        self.assertEqual(stats["collected_but_ineligible"], 1)


if __name__ == "__main__":
    unittest.main()
