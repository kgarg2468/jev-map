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
