import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1] / "benchmarks/06-agent-navigation"


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


cheap = module("agent_cheap", "run_cheap_hints.py")
agents = module("agent_runner", "run_agents.py")


class AgentRunnerTest(unittest.TestCase):
    def test_cheap_hint_scores_require_complete_numeric_response(self):
        self.assertEqual(cheap.parse_scores('{"b0":0.8,"b1":0}', {"b0", "b1"}),
                         {"b0": 0.8, "b1": 0})
        for invalid in ('{"b0":true,"b1":0}', '{"b0":0.8}', '{"b0":2,"b1":0}'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                cheap.parse_scores(invalid, {"b0", "b1"})

    def test_command_failure_and_web_fallback_cannot_be_scored(self):
        failed = {"type": "item.completed", "item": {"type": "command_execution",
                 "command": "graphify query target", "exit_code": 1}}
        web = {"type": "item.completed", "item": {"type": "web_search"}}
        self.assertEqual(agents.tool_compliance([failed, web]), (False, True, 1))
        passed = {"type": "item.completed", "item": {"type": "command_execution",
                 "command": "uvx --from graphifyy==0.9.67 graphify query target", "exit_code": 0}}
        self.assertEqual(agents.tool_compliance([passed]), (True, False, 1))

    def test_answer_schema_and_arm_order(self):
        valid = '{"tests":["tests/test_a.py::test_a"],"evidence":"call path","commands_run":[]}'
        self.assertEqual(agents.parse_answer(valid)["tests"], ["tests/test_a.py::test_a"])
        with self.assertRaises(ValueError):
            agents.parse_answer('{"tests":["x","x"],"evidence":"", "commands_run":[]}')
        self.assertEqual(agents.arm_order("seed", "task"), agents.arm_order("seed", "task"))
        self.assertEqual(set(agents.arm_order("seed", "task")), set(agents.ARMS))
