"""Retrospective comparison on the archived multi-repository candidate pairs.

This is exploratory: the candidate set was selected before this comparator was
chosen, and it excludes pairs linked by jev-map's structural graph.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import time
from collections import defaultdict, deque
from pathlib import Path

from benchmarks.archive import staged_round
from jev_map.enrich import tokens
from jev_map.index import build

PROJECT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT / "benchmarks/03-multi-repo-relationships/repositories.json"
PAIRS = PROJECT / "benchmarks/03-multi-repo-relationships/rounds/round-01/pairs.json"
GRAPHIFY_VERSION = "0.9.67"
RELATION_SETS = {"calls": frozenset({"calls"}),
                 "calls_and_indirect": frozenset({"calls", "indirect_call"})}


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def graphify_id(symbol_id: str) -> str:
    """Graphify 0.9.67's Python symbol ID from a path and qualified name."""
    path, separator, name = symbol_id.partition("::")
    if not separator or not path.endswith(".py") or not name:
        raise ValueError(f"Invalid symbol ID: {symbol_id}")
    return re.sub(r"[^a-z0-9]+", "_", f"{path[:-3]}.{name}".lower()).strip("_")


def graph_node(graph: dict, symbol_id: str) -> str | None:
    """Refuse ID collisions and unrelated nodes instead of counting them as hits."""
    path, _, name = symbol_id.partition("::")
    node_id = graphify_id(symbol_id)
    matches = [node for node in graph["nodes"] if node["id"] == node_id]
    if len(matches) != 1:
        return None
    node = matches[0]
    label = node.get("label", "").lstrip(".").split("(")[0]
    if node.get("source_file") != path or label != name.split(".")[-1] or not node.get("_callable"):
        return None
    return node_id


def call_path(graph: dict, start: str | None, target: str | None,
              relations: frozenset[str]) -> list[dict] | None:
    if start is None or target is None:
        return None
    adjacency: dict[str, list[dict]] = defaultdict(list)
    for edge in graph["edges"]:
        if edge["relation"] in relations:
            adjacency[edge["source"]].append(edge)
    queue = deque([start])
    previous: dict[str, dict | None] = {start: None}
    while queue:
        current = queue.popleft()
        for edge in adjacency[current]:
            peer = edge["target"]
            if peer in previous:
                continue
            previous[peer] = edge
            if peer == target:
                path = []
                while peer != start:
                    step = previous[peer]
                    path.append({key: step[key] for key in ("source", "target", "relation", "confidence")})
                    peer = step["source"]
                return list(reversed(path))
            queue.append(peer)
    return None


def lexical_scores(data: dict, pair_rows: list[dict]) -> dict[tuple[str, str], float]:
    """The original unsupervised IDF overlap, evaluated without oracle labels."""
    tests = [symbol for symbol in data["symbols"].values() if symbol["kind"] == "test"]
    test_words = {test["id"]: tokens(test["name"] + " " + test["text"]) for test in tests}
    document_frequency: dict[str, int] = defaultdict(int)
    for words in test_words.values():
        for word in words:
            document_frequency[word] += 1
    scores = {}
    for row in pair_rows:
        function = data["symbols"][row["function"]]
        words = tokens(function["name"] + " " + function["text"])
        common = words & test_words[row["test"]]
        scores[row["function"], row["test"]] = sum(
            math.log(1 + len(tests) / document_frequency[word]) for word in common)
    return scores


def ranking(rows: list[dict], score_key: str, limit: int) -> set[tuple[str, str, str]]:
    ordered = sorted(rows, key=lambda row: (-row[score_key], row["repository"],
                                             row["function"], row["test"]))
    return {(row["repository"], row["function"], row["test"]) for row in ordered[:limit]}


def metrics(rows: list[dict], key: str) -> dict:
    predicted = [row for row in rows if row[key]]
    positives = [row for row in rows if row["observed"]]
    true_positive = sum(row["observed"] for row in predicted)
    return {"emitted": len(predicted), "true_positive": true_positive,
            "false_positive": len(predicted) - true_positive,
            "precision": true_positive / len(predicted) if predicted else None,
            "recall_within_candidates": true_positive / len(positives) if positives else None,
            "functions_with_observed_link": len({(row["repository"], row["function"])
                                                 for row in predicted if row["observed"]})}


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True, timeout=30).strip()


def graphify_environment(source: dict[str, str]) -> dict[str, str]:
    """Allow runtime basics while withholding provider and developer credentials."""
    allowed = {"PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "LC_CTYPE",
               "SSL_CERT_FILE", "SSL_CERT_DIR", "UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR"}
    result = {key: value for key, value in source.items() if key in allowed}
    result["PYTHONNOUSERSITE"] = "1"
    result["UV_OFFLINE"] = "1"
    return result


def portable_log(value: str, root: Path, stage: Path) -> str:
    return (value.replace(str(stage), "<round>")
            .replace(str(root), "<repo>")
            .replace(str(PROJECT), "<project>"))


def run(roots: dict[str, Path], output: Path) -> dict:
    config = json.loads(CONFIG.read_text())
    expected = {repo["name"] for repo in config["repositories"]}
    if set(roots) != expected:
        raise ValueError(f"Expected exactly {sorted(expected)}")
    for repo in config["repositories"]:
        root = roots[repo["name"]]
        if git(root, "rev-parse", "HEAD") != repo["commit"]:
            raise ValueError(f'{repo["name"]} is not at the pinned commit')
        if subprocess.run(["git", "-C", str(root), "diff", "--quiet", "HEAD", "--"],
                          timeout=30).returncode:
            raise ValueError(f'{repo["name"]} has tracked changes')
        untracked = git(root, "ls-files", "--others", "--exclude-standard")
        if untracked:
            raise ValueError(f'{repo["name"]} has untracked input')
    existing = json.loads(PAIRS.read_text())
    rows = [{key: row[key] for key in ("repository", "function", "test", "observed", "score")}
            for row in existing if row["test_eligible"]]
    budget = sum(row["score"] >= config["threshold"] for row in rows)
    with staged_round(output) as stage:
        graphs = {}
        extraction = {}
        lexical = {}
        for repo in config["repositories"]:
            name = repo["name"]
            root = roots[name]
            target = stage / "extraction" / name
            command = ["uvx", "--from", f"graphifyy=={GRAPHIFY_VERSION}", "graphify", "extract",
                       str(root), "--code-only", "--no-cluster", "--max-workers", "2",
                       "--out", str(target)]
            started = time.perf_counter()
            result = subprocess.run(command, text=True, capture_output=True, timeout=180,
                                    env=graphify_environment(os.environ))
            elapsed = time.perf_counter() - started
            write(stage / "logs" / f"{name}.json",
                  {"command": [portable_log(item, root, stage)
                               for item in command], "returncode": result.returncode,
                   "stdout": portable_log(result.stdout, root, stage),
                   "stderr": portable_log(result.stderr, root, stage),
                   "wall_seconds": elapsed})
            if result.returncode:
                raise RuntimeError(f"Graphify failed on {name}: {result.stderr[-1000:]}")
            graph_path = target / "graphify-out/graph.json"
            if not graph_path.is_file():
                raise RuntimeError(f"Graphify did not write a graph for {name}")
            graph = json.loads(graph_path.read_text())
            graphs[name] = graph
            extraction[name] = {"graph_sha256": sha256(graph_path), "nodes": len(graph["nodes"]),
                                "edges": len(graph["edges"]), "wall_seconds": elapsed,
                                "input_tokens": graph.get("input_tokens"),
                                "output_tokens": graph.get("output_tokens")}
            data = build(root)
            repo_rows = [row for row in rows if row["repository"] == name]
            lexical.update({(name, *pair): score for pair, score in lexical_scores(data, repo_rows).items()})
        for row in rows:
            name = row["repository"]
            graph = graphs[name]
            start = graph_node(graph, row["test"])
            target = graph_node(graph, row["function"])
            row["graphify_test_node"] = start
            row["graphify_function_node"] = target
            for kind, relations in RELATION_SETS.items():
                row[f"graphify_{kind}_path"] = call_path(graph, start, target, relations)
                row[f"graphify_{kind}"] = row[f"graphify_{kind}_path"] is not None
            row["lexical_score"] = lexical[name, row["function"], row["test"]]
            row["jev_accepted"] = row["score"] >= config["threshold"]
        lexical_top = ranking(rows, "lexical_score", budget)
        for row in rows:
            row["lexical_at_equal_budget"] = (row["repository"], row["function"], row["test"]) in lexical_top
        summary = {"kind": "retrospective_exploration", "sample_source_sha256": sha256(PAIRS),
                   "graphify_package": f"graphifyy=={GRAPHIFY_VERSION}",
                   "graphify_mode": "extract --code-only --no-cluster --max-workers 2",
                   "eligible_pairs": len(rows), "observed_pairs": sum(row["observed"] for row in rows),
                   "equal_output_budget": budget, "extraction": extraction,
                   "node_mapping": {"test_missing": sum(row["graphify_test_node"] is None for row in rows),
                                    "function_missing": sum(row["graphify_function_node"] is None for row in rows)},
                   "methods": {key: metrics(rows, key) for key in
                               ("jev_accepted", "graphify_calls", "graphify_calls_and_indirect",
                                "lexical_at_equal_budget")},
                   "limits": "Jev-selected, nonstructural candidates only; no fresh random holdout, "
                             "complete-test recall, LLM baseline, agent outcome, or cost equivalence."}
        write(stage / "pairs.json", rows)
        write(stage / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", action="append", required=True, help="name=/absolute/path")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    roots = {}
    for spec in args.repo:
        name, separator, path = spec.partition("=")
        if not separator or name in roots:
            parser.error("Use unique --repo name=/absolute/path arguments")
        roots[name] = Path(path).resolve(strict=True)
    print(json.dumps(run(roots, args.out), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
