"""Check the adapter and scoring rules used by the product comparison."""

import unittest

from pathlib import Path

from benchmarks.graphify_compare import (call_path, graph_node, graphify_environment,
                                         graphify_id, metrics, portable_log, ranking)


class GraphifyComparisonTests(unittest.TestCase):
    def test_symbol_identity_checks_file_label_and_callability(self):
        symbol = "src/pkg/core.py::Thing.run"
        self.assertEqual(graphify_id(symbol), "src_pkg_core_thing_run")
        node = {"id": "src_pkg_core_thing_run", "source_file": "src/pkg/core.py",
                "label": ".run()", "_callable": True}
        self.assertEqual(graph_node({"nodes": [node]}, symbol), node["id"])
        self.assertIsNone(graph_node({"nodes": [node, node]}, symbol))
        self.assertIsNone(graph_node({"nodes": [{**node, "source_file": "elsewhere.py"}]}, symbol))
        self.assertIsNone(graph_node({"nodes": [{**node, "_callable": False}]}, symbol))

    def test_only_directed_call_edges_count_as_execution_path(self):
        graph = {"edges": [
            {"source": "test", "target": "alias", "relation": "calls", "confidence": "EXTRACTED"},
            {"source": "alias", "target": "target", "relation": "indirect_call", "confidence": "INFERRED"},
            {"source": "test", "target": "target", "relation": "imports", "confidence": "EXTRACTED"},
        ]}
        self.assertIsNone(call_path(graph, "test", "target", frozenset({"calls"})))
        self.assertEqual([step["relation"] for step in call_path(
            graph, "test", "target", frozenset({"calls", "indirect_call"}))],
            ["calls", "indirect_call"])
        self.assertIsNone(call_path(graph, "target", "test", frozenset({"calls", "indirect_call"})))

    def test_equal_budget_is_deterministic_and_counts_false_positives(self):
        rows = [{"repository": "r", "function": "f", "test": test,
                 "lexical_score": 1.0, "observed": observed} for test, observed in
                (("b", False), ("a", True), ("c", True))]
        selected = ranking(rows, "lexical_score", 2)
        self.assertEqual(selected, {("r", "f", "a"), ("r", "f", "b")})
        for row in rows:
            row["selected"] = ("r", "f", row["test"]) in selected
        self.assertEqual(metrics(rows, "selected"), {
            "emitted": 2, "true_positive": 1, "false_positive": 1,
            "precision": 0.5, "recall_within_candidates": 0.5,
            "functions_with_observed_link": 1,
        })

    def test_external_graphify_process_does_not_inherit_credentials(self):
        source = {"PATH": "/bin", "HOME": "/tmp/user", "TYPESAFE_API_KEY": "private",
                  "GITHUB_TOKEN": "private", "UV_INDEX_URL": "https://private@example.com"}
        self.assertEqual(graphify_environment(source),
                         {"PATH": "/bin", "HOME": "/tmp/user", "PYTHONNOUSERSITE": "1"})

    def test_portable_log_removes_checkout_and_staging_paths(self):
        value = "/tmp/input/repo/file.py -> /tmp/input/round/graphify-out/graph.json"
        self.assertEqual(portable_log(value, Path("/tmp/input/repo"), Path("/tmp/input/round")),
                         "<repo>/file.py -> <round>/graphify-out/graph.json")


if __name__ == "__main__":
    unittest.main()
