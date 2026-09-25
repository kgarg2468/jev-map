"""Freeze source-only targets for the popular-repository replication.

Same selection rule as benchmark 05, applied to new repositories, with no prior
targets to exclude. Run before any provider call or test-call profiling.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from benchmarks.archive import staged_round
from benchmarks.heldout_freeze import selected_functions, under, verify
from jev_map.enrich import make_request, proposals
from jev_map.index import build, digest

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
CONFIG = HERE / "repositories.json"


def implementation_sha256() -> str:
    files = [PROJECT / "src/jev_map/index.py", PROJECT / "src/jev_map/enrich.py",
             PROJECT / "src/jev_map/provider.py", PROJECT / "benchmarks/archive.py",
             PROJECT / "benchmarks/heldout_freeze.py", Path(__file__)]
    return digest({file.relative_to(PROJECT).as_posix(): file.read_text() for file in files})


def freeze(config: dict, roots: dict[str, Path]) -> dict:
    verify(config, roots)
    entries = []
    for repo in config["repositories"]:
        name = repo["name"]
        data = build(roots[name])
        candidates = {function["id"]: peers for function, peers in
                      proposals(data, config["candidate_limit"])}
        links = {}
        for link in data["links"]:
            if link["evidence"] == "structural":
                links.setdefault(link["function"], []).append(link["test"])
        targets = []
        for function in selected_functions(config, repo, data, set()):
            peers = candidates.get(function["id"], [])
            request = make_request(data, function, peers, config["model"]) if peers else None
            targets.append({"function": function["id"],
                            "structural_tests": sorted(links.get(function["id"], [])),
                            "candidates": [peer["id"] for peer in peers],
                            "request_sha256": digest(request) if request else None})
        tests = sorted(symbol["id"] for symbol in data["symbols"].values()
                       if symbol["kind"] == "test" and under(symbol["path"], repo["test_paths"]))
        entries.append({"name": name, "commit": repo["commit"], "snapshot_sha256": data["snapshot"],
                        "file_hashes": data["files"], "diagnostics": data.get("diagnostics", []),
                        "test_ids": tests, "targets": targets})
    return {"schema": 1, "config_sha256": digest(config),
            "protocol_sha256": hashlib.sha256((HERE / "PROTOCOL.md").read_bytes()).hexdigest(),
            "implementation_sha256": implementation_sha256(), "repositories": entries}


def parse_roots(parser: argparse.ArgumentParser, values: list[str]) -> dict[str, Path]:
    roots = {}
    for value in values:
        name, sep, path = value.partition("=")
        if not sep or name in roots:
            parser.error("Use unique name=/absolute/path repository arguments")
        roots[name] = Path(path).resolve(strict=True)
    return roots


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", action="append", required=True,
                        help="name=/absolute/path to the configured root (subdirectory included)")
    parser.add_argument("--out", type=Path, default=HERE / "rounds/round-00-freeze",
                        help="New, non-existing round directory")
    args = parser.parse_args()
    value = freeze(json.loads(CONFIG.read_text()), parse_roots(parser, args.repo))
    summary = {"targets": sum(len(repo["targets"]) for repo in value["repositories"]),
               "requests": sum(item["request_sha256"] is not None
                               for repo in value["repositories"] for item in repo["targets"]),
               "structural_targets": sum(bool(item["structural_tests"])
                                         for repo in value["repositories"] for item in repo["targets"]),
               "tests": {repo["name"]: len(repo["test_ids"]) for repo in value["repositories"]},
               "diagnostics": {repo["name"]: len(repo["diagnostics"]) for repo in value["repositories"]}}
    with staged_round(args.out) as stage:
        (stage / "freeze.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        (stage / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
