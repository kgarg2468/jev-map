import importlib.util
import unittest
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "benchmarks/06-agent-navigation/freeze.py"
SPEC = importlib.util.spec_from_file_location("agent_navigation_freeze", MODULE)
freeze = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(freeze)
AUDIT = MODULE.with_name("audit_freeze.py")
AUDIT_SPEC = importlib.util.spec_from_file_location("agent_navigation_audit", AUDIT)
audit = importlib.util.module_from_spec(AUDIT_SPEC)
AUDIT_SPEC.loader.exec_module(audit)


class AgentNavigationFreezeTest(unittest.TestCase):
    def test_runnable_id_keeps_inherited_class_and_collapses_parameters(self):
        self.assertEqual(freeze.runnable_test_id("tests/test_cache.py::CacheTest::test_clear"),
                         "tests/test_cache.py::CacheTest::test_clear")
        self.assertEqual(freeze.runnable_test_id("tests/test_x.py::TestX::test_y[value-1]"),
                         "tests/test_x.py::TestX::test_y")
        self.assertIsNone(freeze.runnable_test_id("tests/test_x.py"))
        self.assertEqual(audit.runnable_test_id("tests/test_x.py::TestX[a::b]::test_y[c::d]"),
                         "tests/test_x.py::TestX::test_y")

    def test_oracle_excludes_failed_and_unknown_cases(self):
        symbols = {"core.py::work": {"kind": "function"}}
        passed = {"observed": ["core.py::work"], "thread_coverage_unknown": False,
                  "reports": [{"when": "setup", "outcome": "passed"},
                              {"when": "call", "outcome": "passed"},
                              {"when": "teardown", "outcome": "passed"}]}
        oracle = {"pytest_exit": 0, "cases": {
            "tests/test_core.py::TestCore::test_a[x]": passed,
            "tests/test_core.py::TestCore::test_a[y]": passed,
            "tests/test_core.py::test_failed": {**passed, "reports": [{"when": "call", "outcome": "failed"}]},
            "tests/test_core.py::test_thread": {**passed, "thread_coverage_unknown": True},
        }}
        self.assertEqual(freeze.oracle_links(oracle, symbols),
                         {"core.py::work": {"tests/test_core.py::TestCore::test_a"}})
        oracle["pytest_exit"] = 1
        with self.assertRaisesRegex(ValueError, "exit"):
            freeze.oracle_links(oracle, symbols)
