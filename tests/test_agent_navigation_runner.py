import importlib.util
import json
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parents[1] / "benchmarks/06-agent-navigation"


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


cheap = module("agent_cheap", "run_cheap_hints.py")
agents = module("agent_runner", "run_agents.py")
tool_inputs = module("agent_tool_inputs", "run_tool_inputs.py")


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

    def test_cached_run_requires_exact_effective_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = root / "graph.json"
            graph.write_text('{"nodes": []}')
            task = {"id": "case", "function": "package.py::work"}
            prompt = agents.prompt_for(task, graph, {"target": task["function"], "links": []})
            config = json.loads(agents.CONFIG.read_text())
            slot = root / "spool/case/graphify"
            slot.mkdir(parents=True)
            (slot / "prompt.txt").write_text(prompt)
            cached = {"task": "case", "arm": "graphify", "status": "ok",
                      "input_sha256": agents.effective_input_hash(
                          config["agent_model"], config["agent_effort"], prompt, graph, 180)}
            (slot / "meta.json").write_text(json.dumps(cached))
            self.assertEqual(agents.run_one(Path("/unused"), root, task, "graphify", graph,
                                            root / "spool", 180), cached)
            with self.assertRaisesRegex(ValueError, "Stale cached"):
                agents.run_one(Path("/unused"), root, task, "graphify", graph,
                               root / "spool", 181)
            graph.write_text('{"nodes": [1]}')
            with self.assertRaisesRegex(ValueError, "Stale cached"):
                agents.run_one(Path("/unused"), root, task, "graphify", graph,
                               root / "spool", 180)

    def test_supplied_graph_must_match_fresh_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            supplied = root / "supplied.json"
            supplied.write_bytes(b"correct")

            def fake_extract(argv, *, timeout):
                output = Path(argv[-1]) / "graphify-out"
                output.mkdir(parents=True)
                (output / "graph.json").write_bytes(b"fresh")
                return subprocess.CompletedProcess(argv, 0, "built", ""), 0.1

            with patch.object(tool_inputs, "command", side_effect=fake_extract):
                with self.assertRaisesRegex(ValueError, "does not match"):
                    tool_inputs.verified_graph(root, supplied, "graphifyy==0.9.67")
