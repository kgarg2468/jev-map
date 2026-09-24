"""Score agent answers against the frozen execution oracle after all runs finish."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
from collections import defaultdict
from pathlib import Path

from benchmarks.archive import staged_round
from jev_map.index import digest

HERE = Path(__file__).resolve().parent
FREEZE = HERE / "rounds/round-01-freeze/freeze.json"
RUNS = HERE / "rounds/round-06-agent-runs"
INPUTS = HERE / "rounds/round-02-tool-inputs"
CHEAP = HERE / "rounds/round-03-cheap-hints"
ARMS = ("graphify", "jev", "cheap")
LIST_PRICES_PER_MILLION = {
    "jev-1.13.0": {"input": 0.042, "cached_input": 0.042, "output": 0.0},
    "gpt-5.6-luna": {"input": 0.20, "cached_input": 0.02, "output": 1.20},
    "gpt-6-sol": {"input": 2.00, "cached_input": 0.20, "output": 10.00},
}
PRICE_SOURCES = {
    "jev-1.13.0": "https://typesafe.ai/blog/introducing-system-one-models-and-jev",
    "gpt-5.6-luna": "https://developers.openai.com/api/docs/models/gpt-5.6-luna",
    "gpt-6-sol": "https://developers.openai.com/api/docs/pricing",
}


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


audit = module("agent_audit", HERE / "audit_freeze.py")
runner = module("agent_runner", HERE / "run_agents.py")


def verify_round(path: Path) -> None:
    manifest = json.loads((path / "completion.json").read_text())
    if manifest.get("status") != "complete":
        raise ValueError(f"Incomplete round: {path}")
    actual = {item.relative_to(path).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
              for item in path.rglob("*") if item.is_file() and item.name != "completion.json"}
    if actual != manifest["files"]:
        raise ValueError(f"Round checksum mismatch: {path}")


def eligible_case(row: dict) -> bool:
    reports = row.get("reports", [])
    return (not row.get("thread_coverage_unknown")
            and any(item["when"] == "call" and item["outcome"] == "passed" for item in reports)
            and all(item["outcome"] == "passed" for item in reports))


def test_statuses(oracle: dict) -> tuple[set[str], set[str]]:
    """Return tests with any eligible case and those with any unknown case."""
    eligible, unknown = set(), set()
    for nodeid, row in oracle["cases"].items():
        test = audit.runnable_test_id(nodeid)
        if test is None:
            continue
        (eligible if eligible_case(row) else unknown).add(test)
    return eligible, unknown


def observed_links(oracle: dict) -> dict[str, set[str]]:
    if oracle.get("pytest_exit") != 0:
        raise ValueError("Profiled suite failed")
    result: dict[str, set[str]] = defaultdict(set)
    for nodeid, row in oracle["cases"].items():
        test = audit.runnable_test_id(nodeid)
        if test is not None and eligible_case(row):
            for function in row["observed"]:
                result[function].add(test)
    return result


def score_answer(answer: dict | None, observed: set[str],
                 eligible: set[str], unknown: set[str]) -> dict:
    tests = answer["tests"] if answer is not None else []
    normalized = [audit.runnable_test_id(test) for test in tests]
    positions = [index + 1 for index, test in enumerate(normalized) if test in observed]
    return {"tests": tests, "hit1": bool(positions and positions[0] == 1),
            "hit3": bool(positions), "reciprocal_rank": 1 / positions[0] if positions else 0,
            "false_suggestions": sum(test in eligible and test not in unknown and test not in observed
                                     for test in normalized),
            "unknown_suggestions": sum(test in unknown and test not in observed for test in normalized),
            "invalid_ids": sum(test not in eligible and test not in unknown for test in normalized)}


def bootstrap_interval(rows: list[dict], a: str, b: str, *, seed: str, resamples: int = 10000) -> list[float]:
    by_repo: dict[str, list[dict]] = {}
    for row in rows:
        by_repo.setdefault(row["repo"], []).append(row)
    rng = random.Random(seed + "\0" + a + "\0" + b)
    values = []
    total = len(rows)
    for _ in range(resamples):
        difference = 0
        for repo_rows in by_repo.values():
            for _ in repo_rows:
                item = rng.choice(repo_rows)
                difference += item["arms"][a]["hit1"] - item["arms"][b]["hit1"]
        values.append(difference / total)
    values.sort()
    return [values[int(0.025 * (resamples - 1))], values[int(0.975 * (resamples - 1))]]


def usage_totals(rows: list[dict]) -> dict:
    result = {}
    for arm in ARMS:
        usage = [row["arms"][arm]["usage"] or {} for row in rows]
        result[arm] = {"input_tokens": sum(item.get("input_tokens", 0) for item in usage),
                       "cached_input_tokens": sum(item.get("cached_input_tokens", 0) for item in usage),
                       "output_tokens": sum(item.get("output_tokens", 0) for item in usage),
                       "unknown_usage_runs": sum(not item for item in usage),
                       "agent_wall_seconds": sum(row["arms"][arm]["wall_seconds"] for row in rows)}
    return result


def list_price_cost(usage: dict, model: str) -> float:
    price = LIST_PRICES_PER_MILLION[model]
    total = usage.get("input_tokens", 0)
    cached = usage.get("cached_input_tokens", 0)
    output = usage.get("output_tokens", 0)
    if any(type(value) is not int or value < 0 for value in (total, cached, output)) or cached > total:
        raise ValueError("Invalid token usage for price estimate")
    return ((total - cached) * price["input"] + cached * price["cached_input"]
            + output * price["output"]) / 1_000_000


def checked_jev_receipts(receipt_dir: Path, expected_targets: set[str]) -> tuple[int, float]:
    """Count only the exact canonical receipts for this frozen task set."""
    tokens, wall = 0, 0.0
    found = set()
    for path in receipt_dir.glob("*.json"):
        if len(path.stem) != 64:
            continue  # Individual attempt logs have a timestamp suffix.
        receipt = json.loads(path.read_text())
        target = receipt["request"]["state"]["A"]["id"]
        if (target not in expected_targets or target in found
                or receipt.get("status") != "ok"
                or receipt.get("request_sha256") != path.stem
                or digest(receipt["request"]) != path.stem
                or receipt.get("response_sha256") != digest(receipt["response"])):
            raise ValueError(f"Unexpected Jev receipt: {path}")
        found.add(target)
        usage = receipt["response"].get("usage", {})
        count = usage.get("input_tokens")
        if type(count) is not int or count < 0:
            raise ValueError("Missing Jev input token usage")
        tokens += count
        wall += receipt.get("wall_seconds", 0.0)
    if found != expected_targets:
        raise ValueError(f"Jev receipts do not match frozen targets: {receipt_dir}")
    return tokens, wall


def hint_costs() -> dict:
    jev_tokens = 0
    jev_provider_wall = 0.0
    refresh_wall = 0.0
    freeze = json.loads(FREEZE.read_text())
    for entry in freeze["repositories"]:
        name = entry["name"]
        refresh_wall += json.loads((INPUTS / f"{name}-refresh-time.json").read_text())["wall_seconds"]
        count, seconds = checked_jev_receipts(
            INPUTS / name / "receipts", {task["function"] for task in entry["tasks"]})
        jev_tokens += count
        jev_provider_wall += seconds
    jev_runs = json.loads((INPUTS / "summary.json").read_text())["tasks"]
    cheap = json.loads((CHEAP / "summary.json").read_text())["tasks"]
    if any(item["usage"] is None for item in cheap):
        raise ValueError("Missing cheap LLM usage")
    cheap_usage = {key: sum(item["usage"].get(key, 0) for item in cheap)
                   for key in ("input_tokens", "cached_input_tokens", "output_tokens")}
    return {"pricing_as_of": "2026-09-24", "pricing_basis": "public API list-price equivalent; actual Codex billing may differ",
            "sources": PRICE_SOURCES,
            "jev": {"input_tokens": jev_tokens,
                    "one_time_map_refresh_wall_seconds": refresh_wall,
                    "provider_wall_seconds_unique": jev_provider_wall,
                    "tool_wall_seconds": sum(item["wall_seconds"] for item in jev_runs),
                    "new_requests_in_archived_runner": sum(item["usage"]["requests"] for item in jev_runs),
                    "cache_hits_in_archived_runner": sum(item["usage"]["cache_hits"] for item in jev_runs),
                    "list_price_usd": list_price_cost({"input_tokens": jev_tokens}, "jev-1.13.0")},
            "cheap_llm": {**cheap_usage,
                          "wall_seconds": sum(item["wall_seconds"] for item in cheap),
                          "list_price_usd": list_price_cost(cheap_usage, "gpt-5.6-luna")}}


def summarise(rows: list[dict], key: str | None = None) -> dict:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row[key] if key else "all", []).append(row)
    return {name: {arm: {"n": len(items),
                         "hit1": sum(item["arms"][arm]["hit1"] for item in items),
                         "hit3": sum(item["arms"][arm]["hit3"] for item in items),
                         "mrr": sum(item["arms"][arm]["reciprocal_rank"] for item in items) / len(items),
                         "noncompliant": sum(not item["arms"][arm]["compliant"] for item in items)}
                   for arm in ARMS} for name, items in groups.items()}


def run(oracles: dict[str, Path], out: Path) -> dict:
    for path in (FREEZE.parent, RUNS, INPUTS, CHEAP, HERE / "rounds/round-02-freeze-audit"):
        verify_round(path)
    freeze = json.loads(FREEZE.read_text())
    agent_summary = json.loads((RUNS / "summary.json").read_text())
    agents = {(item["task"], item["arm"]): item for item in agent_summary["jobs"]}
    if len(agents) != 3 * sum(len(entry["tasks"]) for entry in freeze["repositories"]):
        raise ValueError("Agent run set is incomplete or duplicated")
    rows = []
    for entry in freeze["repositories"]:
        name = entry["name"]
        raw = oracles[name].read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["oracle_sha256"]:
            raise ValueError(f"{name} oracle differs from freeze")
        oracle = json.loads(raw)
        observed = observed_links(oracle)
        eligible, unknown = test_statuses(oracle)
        for task in entry["tasks"]:
            if task["function"] not in observed:
                raise ValueError(f"Frozen task lacks an observed eligible test: {task['id']}")
            arm_scores = {}
            for arm in ARMS:
                item = agents[(task["id"], arm)]
                slot = RUNS / "runs" / task["id"] / arm
                events = [json.loads(line) for line in (slot / "events.jsonl").read_text().splitlines()
                          if line.startswith("{")]
                graphify_used, web_used, command_count = runner.tool_compliance(events)
                commands = [event["item"].get("command", "") for event in events
                            if event.get("type") == "item.completed"
                            and event.get("item", {}).get("type") == "command_execution"]
                forbidden_access = any(".jev-map" in command or "/tmp/jev-agent-oracle" in command
                                       for command in commands)
                compliant = item["status"] == "ok" and graphify_used and not web_used and not forbidden_access
                answer = item["answer"] if compliant else None
                if answer is not None and answer != runner.parse_answer((slot / "answer.txt").read_text()):
                    raise ValueError(f"Agent answer mismatch: {task['id']} {arm}")
                arm_scores[arm] = {**score_answer(answer, observed[task["function"]], eligible, unknown),
                                   "status": item["status"], "compliant": compliant,
                                   "graphify_used": graphify_used,
                                   "web_used": web_used, "command_count": command_count,
                                   "forbidden_access": forbidden_access,
                                   "ran_pytest": any("pytest" in command for command in commands),
                                   "used_rg": any("rg " in command for command in commands),
                                   "wall_seconds": item["wall_seconds"], "usage": item["usage"]}
            rows.append({"task": task["id"], "repo": name, "stratum": task["stratum"],
                         "function": task["function"], "observed_tests": sorted(observed[task["function"]]),
                         "arms": arm_scores})
    totals = summarise(rows)["all"]
    intervals = {base: bootstrap_interval(rows, "jev", base, seed="jev-agent-navigation-bootstrap-v1")
                 for base in ("graphify", "cheap")}
    differences = {base: (totals["jev"]["hit1"] - totals[base]["hit1"]) / len(rows)
                   for base in ("graphify", "cheap")}
    by_repo = summarise(rows, "repo")
    positive_repos = sum(all(by_repo[name]["jev"]["hit1"] > by_repo[name][base]["hit1"]
                            for base in ("graphify", "cheap")) for name in by_repo)
    noncompliant = sum(totals[arm]["noncompliant"] for arm in ARMS)
    win = (noncompliant == 0 and all(differences[base] >= 0.10 and intervals[base][0] > 0
                                    for base in ("graphify", "cheap")) and positive_repos >= 2)
    result = {"schema": 1, "tasks": len(rows), "totals": totals,
              "by_repository": by_repo, "by_stratum": summarise(rows, "stratum"),
              "jev_hit1_difference": differences, "paired_bootstrap_95": intervals,
              "positive_repositories_against_both": positive_repos,
              "noncompliant_runs": noncompliant,
              "verdict": "pilot_win" if win else "inconclusive_or_negative",
              "agent_usage": usage_totals(rows), "hint_costs": hint_costs(), "rows": rows}
    result["agent_list_price_usd"] = {
        arm: list_price_cost(usage, "gpt-6-sol")
        for arm, usage in result["agent_usage"].items()}
    with staged_round(out) as stage:
        for name, path in oracles.items():
            (stage / f"{name}-oracle.json").write_bytes(path.read_bytes())
        (stage / "score.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle", action="append", required=True)
    parser.add_argument("--out", type=Path, default=HERE / "rounds/round-07-score")
    args = parser.parse_args()
    oracles = {}
    for item in args.oracle:
        name, sep, path = item.partition("=")
        if not sep or name in oracles:
            parser.error("Expected unique name=/absolute/path")
        oracles[name] = Path(path)
    value = run(oracles, args.out)
    print(json.dumps({key: value[key] for key in ("tasks", "totals", "jev_hit1_difference",
                                                    "paired_bootstrap_95", "verdict")}, indent=2))


if __name__ == "__main__":
    main()
