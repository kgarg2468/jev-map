import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from support import TemporaryRepository

STUDY_PATH = Path(__file__).resolve().parents[1] / "benchmarks/03-multi-repo-relationships/study.py"
SPEC = importlib.util.spec_from_file_location("multirepo_study", STUDY_PATH)
STUDY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STUDY)


class MultiRepositoryStudyTest(TemporaryRepository):
    def test_path_roots_are_component_bounded(self):
        self.assertTrue(STUDY.under("src/pkg/core.py", ["src/pkg"]))
        self.assertFalse(STUDY.under("src/pkg_extra/core.py", ["src/pkg"]))
        self.assertFalse(STUDY.under("src/pkg/core.py", []))

    def test_selector_and_counts(self):
        self.assertEqual(STUDY.selector("tests/test_core.py::TestCore.test_value"),
                         "tests/test_core.py::TestCore::test_value")
        rows = [
            {"test_eligible": True, "score": 0.9, "accepted": True, "observed": True},
            {"test_eligible": True, "score": 0.8, "accepted": True, "observed": False},
            {"test_eligible": True, "score": 0.2, "accepted": False, "observed": True},
            {"test_eligible": False, "score": 0.9, "accepted": True, "observed": True},
        ]
        result = STUDY.counts(rows)
        self.assertEqual(result["candidate_pairs"], 4)
        self.assertEqual(result["test_eligible_pairs"], 3)
        self.assertEqual(result["scored_eligible_pairs"], 3)
        self.assertEqual(result["test_eligible_fraction"], 0.75)
        self.assertEqual(result["accepted_observed"], 1)
        self.assertEqual(result["accepted_not_observed"], 1)
        self.assertEqual(result["rejected_observed"], 1)
        self.assertEqual(result["accepted_observed_fraction"], 0.5)

    def test_test_eligibility_and_reason_are_consistent(self):
        eligible = {"returncode": 0, "timed_out": False, "call_passed": True}
        skipped = {"returncode": 0, "timed_out": False, "call_passed": False}
        failed = {"returncode": 1, "timed_out": False, "call_passed": False}
        timed_out = {"returncode": None, "timed_out": True, "call_passed": False}
        self.assertTrue(STUDY.test_eligible(eligible))
        self.assertIsNone(STUDY.ineligible_reason(eligible))
        self.assertEqual(STUDY.ineligible_reason(skipped), "no_passing_call_phase")
        self.assertEqual(STUDY.ineligible_reason(failed), "failed_or_unselected")
        self.assertEqual(STUDY.ineligible_reason(timed_out), "timed_out")

    def test_reconstruct_rejects_truncated_or_duplicate_freeze(self):
        config = json.loads((STUDY_PATH.parent / "repositories.json").read_text())
        frozen = json.loads((STUDY_PATH.parent / "freeze.json").read_text())
        roots = {repo["name"]: self.root for repo in config["repositories"]}
        original_verify = STUDY.verify_repositories
        original_build = STUDY.build
        original_implementation_hash = STUDY.implementation_hash
        try:
            STUDY.verify_repositories = lambda _config, _roots: None
            first = frozen["repositories"][0]
            STUDY.build = lambda _root: {
                "snapshot": first["corpus_sha256"], "files": first["file_hashes"],
            }
            STUDY.implementation_hash = lambda: frozen["implementation_sha256"]
            removed = frozen["repositories"][0]["selected"].pop()
            with self.assertRaisesRegex(ValueError, "exactly 24"):
                STUDY.reconstruct(config, frozen, roots)
            frozen["repositories"][0]["selected"].append(removed)
            frozen["repositories"][0]["selected"][1]["function"] = first["selected"][0]["function"]
            with self.assertRaisesRegex(ValueError, "functions must be unique"):
                STUDY.reconstruct(config, frozen, roots)
        finally:
            STUDY.verify_repositories = original_verify
            STUDY.build = original_build
            STUDY.implementation_hash = original_implementation_hash

    def test_profile_plugin_observes_exact_qualified_call(self):
        self.write("pkg.py", "class Cleaner:\n    def compact(self, text):\n        return text.strip()\n")
        self.write("test_pkg.py", "from pkg import Cleaner\ndef test_compact():\n    assert Cleaner().compact(' x ') == 'x'\n")
        output = self.root / "trace.json"
        environment = STUDY.clean_environment(self.root, {"pythonpath": ["."]}, output)
        run = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_pkg.py::test_compact",
                              "-p", "profile_plugin"], cwd=self.root, env=environment,
                             text=True, capture_output=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        trace = json.loads(output.read_text())
        self.assertIn("pkg.py::Cleaner.compact", trace["observed"])
        self.assertTrue(any(report["when"] == "call" and report["outcome"] == "passed"
                            for report in trace["reports"]))

    def test_profile_plugin_discloses_skipped_call_phase(self):
        self.write("test_skip.py", "import pytest\n@pytest.mark.skip\ndef test_skip():\n    pass\n")
        output = self.root / "trace.json"
        environment = STUDY.clean_environment(self.root, {"pythonpath": ["."]}, output)
        run = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_skip.py::test_skip",
                              "-p", "profile_plugin"], cwd=self.root, env=environment,
                             text=True, capture_output=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        trace = json.loads(output.read_text())
        self.assertFalse(any(report["when"] == "call" and report["outcome"] == "passed"
                             for report in trace["reports"]))

    def test_sensitive_environment_is_removed(self):
        import os
        original = dict(os.environ)
        try:
            os.environ.update(TYPESAFE_API_KEY="secret", FIXTURE_TOKEN="secret", SAFE_VALUE="ok")
            result = STUDY.clean_environment(self.root, {"pythonpath": ["."]})
        finally:
            os.environ.clear()
            os.environ.update(original)
        self.assertNotIn("TYPESAFE_API_KEY", result)
        self.assertNotIn("FIXTURE_TOKEN", result)
        self.assertEqual(result["SAFE_VALUE"], "ok")
