import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from jev_map.index import digest


MODULE = Path(__file__).resolve().parents[1] / "benchmarks/06-agent-navigation/score.py"
SPEC = importlib.util.spec_from_file_location("agent_navigation_score", MODULE)
score = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(score)


class AgentNavigationScoreTest(unittest.TestCase):
    def test_unknown_tests_are_not_false_suggestions(self):
        answer = {"tests": ["tests/test_a.py::test_unknown", "tests/test_a.py::test_hit",
                            "tests/test_a.py::test_false"]}
        result = score.score_answer(answer, {"tests/test_a.py::test_hit"},
                                    {"tests/test_a.py::test_hit", "tests/test_a.py::test_false"},
                                    {"tests/test_a.py::test_unknown"})
        self.assertFalse(result["hit1"])
        self.assertTrue(result["hit3"])
        self.assertEqual(result["reciprocal_rank"], 0.5)
        self.assertEqual(result["false_suggestions"], 1)
        self.assertEqual(result["unknown_suggestions"], 1)

    def test_bootstrap_preserves_paired_repository_tasks(self):
        rows = [{"repo": repo, "arms": {"jev": {"hit1": True},
                                           "graphify": {"hit1": False}}}
                for repo in ("a", "a", "b", "b")]
        self.assertEqual(score.bootstrap_interval(rows, "jev", "graphify", seed="fixed", resamples=100),
                         [1.0, 1.0])

    def test_oracle_excludes_skips_and_unknown_threads(self):
        passed = {"observed": ["core.py::work"], "thread_coverage_unknown": False,
                  "reports": [{"when": "call", "outcome": "passed"}]}
        oracle = {"pytest_exit": 0, "cases": {
            "tests/test_a.py::test_a[x]": passed,
            "tests/test_a.py::test_b": {**passed, "reports": [{"when": "call", "outcome": "skipped"}]},
            "tests/test_a.py::test_c": {**passed, "thread_coverage_unknown": True}}}
        self.assertEqual(score.observed_links(oracle),
                         {"core.py::work": {"tests/test_a.py::test_a"}})

    def test_list_price_uses_cached_token_rate(self):
        estimate = score.list_price_cost({"input_tokens": 1_000_000,
                                          "cached_input_tokens": 500_000,
                                          "output_tokens": 100_000}, "gpt-5.6-luna")
        self.assertAlmostEqual(estimate, 0.23)
        with self.assertRaisesRegex(ValueError, "Invalid"):
            score.list_price_cost({"input_tokens": 1, "cached_input_tokens": 2}, "gpt-5.6-luna")

    def test_jev_cost_rejects_unrelated_or_missing_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipts = Path(temporary)

            def write(target):
                request = {"state": {"A": {"id": target}}}
                response = {"usage": {"input_tokens": 25}}
                request_hash = digest(request)
                (receipts / f"{request_hash}.json").write_text(json.dumps({
                    "request": request, "request_sha256": request_hash,
                    "response": response, "response_sha256": digest(response),
                    "status": "ok", "wall_seconds": 0.1}))

            write("f")
            self.assertEqual(score.checked_jev_receipts(receipts, {"f"}), (25, 0.1))
            with self.assertRaisesRegex(ValueError, "do not match"):
                score.checked_jev_receipts(receipts, {"f", "g"})
            write("unrelated")
            with self.assertRaisesRegex(ValueError, "Unexpected Jev receipt"):
                score.checked_jev_receipts(receipts, {"f"})
