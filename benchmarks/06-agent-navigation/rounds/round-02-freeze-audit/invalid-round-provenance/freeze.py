"""Freeze an agent-navigation task sample before treatment output exists."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from benchmarks.archive import staged_round
from jev_map.index import build, digest

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]


def in_roots(path: str, roots: list[str]) -> bool:
    return any(path == root or path.startswith(root + "/") for root in roots)


def eligible_test_id(nodeid: str, symbols: dict) -> str | None:
    """Map a passing pytest case, including parametrized methods, to a source test."""
    parts = nodeid.split("::")
    if len(parts) < 2:
        return None
    parts[-1] = parts[-1].split("[", 1)[0]
    ident = parts[0] + "::" + ".".join(parts[1:])
    return ident if ident in symbols and symbols[ident]["kind"] == "test" else None


def oracle_links(oracle: dict, symbols: dict) -> dict[str, set[str]]:
    if oracle.get("pytest_exit") != 0:
        raise ValueError("Profiled test suite did not exit successfully")
    links: dict[str, set[str]] = {}
    for nodeid, row in oracle["cases"].items():
        test = eligible_test_id(nodeid, symbols)
        reports = row.get("reports", [])
        if (test is None or row.get("thread_coverage_unknown")
                or not any(item["when"] == "call" and item["outcome"] == "passed" for item in reports)
                or any(item["outcome"] not in {"passed"} for item in reports)):
            continue
        for function in row["observed"]:
            if function in symbols and symbols[function]["kind"] == "function":
                links.setdefault(function, set()).add(test)
    return links


def selected(config: dict, repo: dict, data: dict, oracle: dict) -> list[dict]:
    observed = oracle_links(oracle, data["symbols"])
    structural = {link["function"] for link in data["links"] if link["evidence"] == "structural"}
    result = []
    for stratum, count in config["per_repository"].items():
        pool = [ident for ident, symbol in data["symbols"].items()
                if symbol["kind"] == "function" and in_roots(symbol["path"], repo["source_roots"])
                and ident in observed and (ident in structural) == (stratum == "structural_path")]
        pool.sort(key=lambda ident: hashlib.sha256(
            f'{config["seed"]}\0{repo["name"]}\0{stratum}\0{ident}'.encode()).hexdigest())
        if len(pool) < count:
            raise ValueError(f'{repo["name"]} has only {len(pool)} tasks for {stratum}')
        result.extend({"id": f'{repo["name"]}-{stratum[:1]}-{index + 1:02d}',
                       "function": ident, "stratum": stratum}
                      for index, ident in enumerate(pool[:count]))
    return sorted(result, key=lambda item: item["id"])


def freeze(config: dict, roots: dict[str, Path], oracles: dict[str, Path]) -> dict:
    if set(roots) != {repo["name"] for repo in config["repositories"]} or set(oracles) != set(roots):
        raise ValueError("Repository and oracle arguments must match the configuration")
    entries = []
    for repo in config["repositories"]:
        name = repo["name"]
        root = roots[name].resolve(strict=True)
        commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        if commit != repo["commit"]:
            raise ValueError(f"{name} checkout differs from pinned commit")
        if subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                          capture_output=True, text=True, check=True).stdout.strip():
            raise ValueError(f"{name} checkout has uncommitted files")
        data = build(root)
        oracle_bytes = oracles[name].read_bytes()
        oracle = json.loads(oracle_bytes)
        entries.append({"name": name, "commit": commit, "snapshot_sha256": data["snapshot"],
                        "file_hashes": data["files"], "oracle_sha256": hashlib.sha256(oracle_bytes).hexdigest(),
                        "profiled_cases": len(oracle["cases"]),
                        "tasks": selected(config, repo, data, oracle)})
    return {"schema": 1, "config_sha256": digest(config),
            "protocol_sha256": hashlib.sha256((HERE / "PROTOCOL.md").read_bytes()).hexdigest(),
            "freeze_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "repositories": entries}


def parse_pairs(values: list[str]) -> dict[str, Path]:
    pairs = {}
    for item in values:
        name, separator, path = item.partition("=")
        if not separator or not name or name in pairs:
            raise ValueError("Expected unique name=/absolute/path arguments")
        pairs[name] = Path(path).resolve(strict=True)
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", action="append", required=True)
    parser.add_argument("--oracle", action="append", required=True)
    parser.add_argument("--out", type=Path, default=HERE / "rounds/round-00-freeze")
    args = parser.parse_args()
    config = json.loads((HERE / "config.json").read_text())
    value = freeze(config, parse_pairs(args.repo), parse_pairs(args.oracle))
    summary = {"repositories": len(value["repositories"]),
               "tasks": sum(len(item["tasks"]) for item in value["repositories"]),
               "strata": {stratum: sum(task["stratum"] == stratum
                                        for entry in value["repositories"] for task in entry["tasks"])
                          for stratum in config["per_repository"]}}
    with staged_round(args.out) as stage:
        (stage / "freeze.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        (stage / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
