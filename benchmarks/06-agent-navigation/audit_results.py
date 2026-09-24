"""Independently reconstruct top-one hits and tool use from raw agent traces."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from benchmarks.archive import staged_round

HERE = Path(__file__).resolve().parent
ROUNDS = HERE / "rounds"
ARMS = ("graphify", "jev", "cheap")


def unparameterize(nodeid: str) -> str:
    result = []
    depth = 0
    for char in nodeid:
        if char == "[":
            depth += 1
        elif char == "]" and depth:
            depth -= 1
        elif depth == 0:
            result.append(char)
    return "".join(result)


def observed(oracle: dict, function: str) -> set[str]:
    tests = set()
    for nodeid, row in oracle["cases"].items():
        reports = row.get("reports", [])
        if (not row.get("thread_coverage_unknown") and function in row["observed"]
                and any(report["when"] == "call" and report["outcome"] == "passed" for report in reports)
                and all(report["outcome"] == "passed" for report in reports)):
            tests.add(unparameterize(nodeid))
    return tests


def quantiles(values: list[float]) -> list[float]:
    values = sorted(values)
    return [values[int(0.025 * (len(values) - 1))], values[int(0.975 * (len(values) - 1))]]


def wall_interval(rows: list[dict], arm: str, *, seed: str, resamples: int = 10000) -> list[float]:
    groups = {}
    for row in rows:
        groups.setdefault(row["repo"], []).append(row)
    rng = random.Random(seed + arm)
    samples = []
    for _ in range(resamples):
        delta = 0.0
        for group in groups.values():
            for _ in group:
                item = rng.choice(group)
                delta += item["seconds"][arm] - item["seconds"]["graphify"]
        samples.append(delta / len(rows))
    return quantiles(samples)


def run(out: Path) -> dict:
    freeze = json.loads((ROUNDS / "round-01-freeze/freeze.json").read_text())
    score = json.loads((ROUNDS / "round-07-score/score.json").read_text())
    inputs = json.loads((ROUNDS / "round-02-tool-inputs/summary.json").read_text())
    cheap = json.loads((ROUNDS / "round-03-cheap-hints/summary.json").read_text())
    jev_wall = {item["id"]: item["wall_seconds"] for item in inputs["tasks"]}
    cheap_wall = {item["id"]: item["wall_seconds"] for item in cheap["tasks"]}
    results = []
    hits = {arm: 0 for arm in ARMS}
    tool_counts = {arm: {"graphify": 0, "pytest": 0, "rg": 0, "web": 0, "forbidden": 0}
                   for arm in ARMS}
    for repo in freeze["repositories"]:
        name = repo["name"]
        oracle = json.loads((ROUNDS / f"round-07-score/{name}-oracle.json").read_text())
        refresh = json.loads((ROUNDS / f"round-02-tool-inputs/{name}-refresh-time.json").read_text())["wall_seconds"]
        for task in repo["tasks"]:
            target = task["function"]
            actual = observed(oracle, target)
            seconds = {}
            first = {}
            for arm in ARMS:
                slot = ROUNDS / "round-06-agent-runs/runs" / task["id"] / arm
                meta = json.loads((slot / "meta.json").read_text())
                if meta["status"] != "ok":
                    raise ValueError(f"Incomplete agent: {task['id']} {arm}")
                answer = json.loads((slot / "answer.txt").read_text())
                suggested = answer["tests"]
                first[arm] = bool(suggested and unparameterize(suggested[0]) in actual)
                hits[arm] += first[arm]
                events = [json.loads(line) for line in (slot / "events.jsonl").read_text().splitlines()
                          if line.startswith("{")]
                commands = [e["item"] for e in events if e.get("type") == "item.completed"
                            and e.get("item", {}).get("type") == "command_execution"]
                strings = [item.get("command", "") for item in commands]
                tool_counts[arm]["graphify"] += any(item.get("exit_code") == 0 and
                                                    ("graphify query" in item.get("command", "")
                                                     or "graphify explain" in item.get("command", ""))
                                                    for item in commands)
                tool_counts[arm]["pytest"] += any("pytest" in cmd for cmd in strings)
                tool_counts[arm]["rg"] += any("rg " in cmd for cmd in strings)
                tool_counts[arm]["web"] += any(e.get("item", {}).get("type") in {"web_search", "browser"}
                                                for e in events)
                tool_counts[arm]["forbidden"] += any(".jev-map" in cmd or "/tmp/jev-agent-oracle" in cmd
                                                      for cmd in strings)
                seconds[arm] = meta["wall_seconds"]
            seconds["jev"] += jev_wall[task["id"]] + refresh / len(repo["tasks"])
            seconds["cheap"] += cheap_wall[task["id"]]
            results.append({"task": task["id"], "repo": name, "hit1": first, "seconds": seconds})
    expected = {arm: score["totals"][arm]["hit1"] for arm in ARMS}
    if hits != expected:
        raise ValueError(f"Independent hit count {hits} differs from scored {expected}")
    if any(tool_counts[arm]["graphify"] != len(results) or tool_counts[arm]["web"]
           or tool_counts[arm]["forbidden"] for arm in ARMS):
        raise ValueError("Agent tool use violates the frozen protocol")
    wall = {arm: {"total_seconds": sum(row["seconds"][arm] for row in results),
                  "mean_paired_difference_vs_graphify_seconds":
                  sum(row["seconds"][arm] - row["seconds"]["graphify"] for row in results) / len(results),
                  "paired_bootstrap_95_seconds": wall_interval(results, arm, seed="jev-agent-wall-v1")}
            for arm in ("jev", "cheap")}
    report = {"tasks": len(results), "independent_hit1": hits,
              "tool_use_runs": tool_counts, "end_to_end_wall": wall,
              "score_code_sha256": hashlib.sha256((HERE / "score.py").read_bytes()).hexdigest(),
              "rows": results}
    with staged_round(out) as stage:
        (stage / "audit.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROUNDS / "round-08-agent-audit")
    args = parser.parse_args()
    result = run(args.out)
    print(json.dumps({key: result[key] for key in ("tasks", "independent_hit1",
                                                   "tool_use_runs", "end_to_end_wall")}, indent=2))


if __name__ == "__main__":
    main()
