"""Verify the published task IDs under corrected runnable-test handling."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from benchmarks.archive import staged_round
from jev_map.index import build

HERE = Path(__file__).resolve().parent


def runnable_test_id(nodeid: str) -> str | None:
    if "::" not in nodeid:
        return None
    result = []
    depth = 0
    for char in nodeid:
        if char == "[":
            depth += 1
        elif char == "]" and depth:
            depth -= 1
        elif depth == 0:
            result.append(char)
    return "".join(result) if depth == 0 else None


def in_roots(path: str, roots: list[str]) -> bool:
    return any(path == root or path.startswith(root + "/") for root in roots)


def eligible_links(oracle: dict, symbols: dict) -> dict[str, set[str]]:
    if oracle.get("pytest_exit") != 0:
        raise ValueError("Profiled suite failed")
    result: dict[str, set[str]] = {}
    for nodeid, row in oracle["cases"].items():
        test = runnable_test_id(nodeid)
        reports = row.get("reports", [])
        if (not test or row.get("thread_coverage_unknown")
                or not any(item["when"] == "call" and item["outcome"] == "passed" for item in reports)
                or any(item["outcome"] != "passed" for item in reports)):
            continue
        for function in row["observed"]:
            if function in symbols and symbols[function]["kind"] == "function":
                result.setdefault(function, set()).add(test)
    return result


def corrected_tasks(config: dict, repo: dict, data: dict, oracle: dict) -> list[dict]:
    observed = eligible_links(oracle, data["symbols"])
    structural = {link["function"] for link in data["links"]
                  if link["evidence"] == "structural"
                  and in_roots(link["test"].split("::", 1)[0], repo["test_roots"])}
    result = []
    for stratum, count in config["per_repository"].items():
        pool = [ident for ident, symbol in data["symbols"].items()
                if symbol["kind"] == "function" and in_roots(symbol["path"], repo["source_roots"])
                and ident in observed and (ident in structural) == (stratum == "structural_path")]
        pool.sort(key=lambda ident: hashlib.sha256(
            f'{config["seed"]}\0{repo["name"]}\0{stratum}\0{ident}'.encode()).hexdigest())
        if len(pool) < count:
            raise ValueError(f"Too few corrected tasks in {repo['name']} {stratum}")
        result.extend({"id": f'{repo["name"]}-{stratum[:1]}-{index + 1:02d}',
                       "function": ident, "stratum": stratum}
                      for index, ident in enumerate(pool[:count]))
    return sorted(result, key=lambda item: item["id"])


def collect(root: Path) -> tuple[set[str], str]:
    command = [str(root / ".venv-bench/bin/python"), "-m", "pytest", "--collect-only", "-q"]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f"Collection failed: {result.stderr[:300]}")
    nodeids = {line for line in result.stdout.splitlines()
               if "::" in line and line.split("::", 1)[0].endswith(".py")}
    return nodeids, result.stdout


def run(roots: dict[str, Path], oracles: dict[str, Path], historical: dict[str, Path], out: Path) -> dict:
    config = json.loads((HERE / "config.json").read_text())
    freeze = json.loads((HERE / "rounds/round-01-freeze/freeze.json").read_text())
    invalid = json.loads((HERE / "rounds/round-00-freeze/freeze.json").read_text())
    if set(roots) != set(oracles) or set(roots) != {repo["name"] for repo in config["repositories"]}:
        raise ValueError("Repository and oracle names must match configuration")
    for name, key in (("freeze.py", "freeze_code_sha256"), ("PROTOCOL.md", "protocol_sha256")):
        if hashlib.sha256(historical[name].read_bytes()).hexdigest() != invalid[key]:
            raise ValueError(f"Historical {name} does not match the invalid round's hash")
    summary = {"historical_inputs_verified": True, "repositories": []}
    with staged_round(out) as stage:
        provenance = stage / "invalid-round-provenance"
        provenance.mkdir()
        for name, path in historical.items():
            shutil.copyfile(path, provenance / name)
        for entry in freeze["repositories"]:
            name = entry["name"]
            repo = next(item for item in config["repositories"] if item["name"] == name)
            root = roots[name].resolve(strict=True)
            data = build(root)
            if data["snapshot"] != entry["snapshot_sha256"]:
                raise ValueError(f"{name} source differs from freeze")
            raw = oracles[name].read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry["oracle_sha256"]:
                raise ValueError(f"{name} oracle differs from freeze")
            oracle = json.loads(raw)
            collected, stdout = collect(root)
            (stage / f"{name}-collect.txt").write_text(stdout)
            profiled = set(oracle["cases"])
            corrected = corrected_tasks(config, repo, data, oracle)
            row = {"name": name, "collect_command": ".venv-bench/bin/python -m pytest --collect-only -q",
                   "profile_command": "JEV_MAP_PROFILE_ROOT=<repo> JEV_MAP_PROFILE_OUTPUT=<private oracle> PYTHONPATH=<jev-map>/benchmarks .venv-bench/bin/python -m pytest -q -p full_suite_profile",
                   "collected_cases": len(collected), "profiled_cases": len(profiled),
                   "missing_profiled_ids": sorted(collected - profiled),
                   "uncollected_profiled_ids": sorted(profiled - collected),
                   "selection_unchanged": corrected == entry["tasks"]}
            summary["repositories"].append(row)
            if row["missing_profiled_ids"] or row["uncollected_profiled_ids"] or not row["selection_unchanged"]:
                raise ValueError(f"{name} freeze audit failed")
        (stage / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def pairs(values: list[str]) -> dict[str, Path]:
    result = {}
    for item in values:
        key, sep, path = item.partition("=")
        if not sep or key in result:
            raise ValueError("Expected unique name=/absolute/path")
        result[key] = Path(path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", action="append", required=True)
    parser.add_argument("--oracle", action="append", required=True)
    parser.add_argument("--historical-freeze", type=Path, required=True)
    parser.add_argument("--historical-protocol", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=HERE / "rounds/round-02-freeze-audit")
    args = parser.parse_args()
    summary = run(pairs(args.repo), pairs(args.oracle),
                  {"freeze.py": args.historical_freeze, "PROTOCOL.md": args.historical_protocol}, args.out)
    print(json.dumps({"same_tasks": all(item["selection_unchanged"] for item in summary["repositories"]),
                      "cases": {item["name"]: item["profiled_cases"] for item in summary["repositories"]}}, indent=2))


if __name__ == "__main__":
    main()
