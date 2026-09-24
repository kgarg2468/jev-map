"""Freeze source-only targets for a prospective Graphify + Jev study."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from benchmarks.archive import staged_round
from jev_map.enrich import make_request, proposals
from jev_map.index import build, digest

PROJECT = Path(__file__).resolve().parents[1]
HERE = PROJECT / "benchmarks/05-heldout-toolbelt"
CONFIG = HERE / "repositories.json"
PRIOR_FREEZE = PROJECT / "benchmarks/03-multi-repo-relationships/freeze.json"


def under(path: str, roots: list[str]) -> bool:
    return any(path == root.rstrip("/") or path.startswith(root.rstrip("/") + "/")
               for root in roots)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True, timeout=30).strip()


def verify(config: dict, roots: dict[str, Path]) -> None:
    if set(roots) != {item["name"] for item in config["repositories"]}:
        raise ValueError("Repository arguments differ from configured repositories")
    for item in config["repositories"]:
        root = roots[item["name"]]
        if git(root, "rev-parse", "HEAD") != item["commit"]:
            raise ValueError(f'{item["name"]} is not at its pinned commit')
        if subprocess.run(["git", "-C", str(root), "diff", "--quiet", "HEAD", "--"],
                          timeout=30).returncode:
            raise ValueError(f'{item["name"]} has tracked changes')
        if git(root, "ls-files", "--others", "--exclude-standard"):
            raise ValueError(f'{item["name"]} has untracked input')


def selected_functions(config: dict, repo: dict, data: dict, old_ids: set[str]) -> list[dict]:
    eligible = [symbol for symbol in data["symbols"].values()
                if symbol["kind"] == "function" and under(symbol["path"], repo["source_roots"])
                and not under(symbol["path"], repo["source_excludes"])
                and symbol["id"] not in old_ids]
    eligible.sort(key=lambda symbol: hashlib.sha256(
        f'{config["seed"]}\0{repo["name"]}\0{symbol["id"]}'.encode()).hexdigest())
    count = config["functions_per_repository"]
    if len(eligible) < count:
        raise ValueError(f'{repo["name"]} has only {len(eligible)} eligible functions')
    return eligible[:count]


def implementation_sha256() -> str:
    files = [PROJECT / "src/jev_map/index.py", PROJECT / "src/jev_map/enrich.py",
             PROJECT / "src/jev_map/provider.py", PROJECT / "benchmarks/archive.py",
             Path(__file__)]
    return digest({file.relative_to(PROJECT).as_posix(): file.read_text() for file in files})


def freeze(config: dict, roots: dict[str, Path]) -> dict:
    verify(config, roots)
    prior = json.loads(PRIOR_FREEZE.read_text())
    old = {repo["name"]: {item["function"] for item in repo["selected"]}
           for repo in prior["repositories"]}
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
        for function in selected_functions(config, repo, data, old[name]):
            peers = candidates.get(function["id"], [])
            request = make_request(data, function, peers, config["model"]) if peers else None
            targets.append({"function": function["id"],
                            "structural_tests": sorted(links.get(function["id"], [])),
                            "candidates": [peer["id"] for peer in peers],
                            "request_sha256": digest(request) if request else None})
        tests = sorted(symbol["id"] for symbol in data["symbols"].values()
                       if symbol["kind"] == "test" and under(symbol["path"], repo["test_paths"]))
        entries.append({"name": name, "commit": repo["commit"], "snapshot_sha256": data["snapshot"],
                        "file_hashes": data["files"], "test_ids": tests, "targets": targets})
    return {"schema": 1, "config_sha256": digest(config),
            "protocol_sha256": hashlib.sha256((HERE / "PROTOCOL.md").read_bytes()).hexdigest(),
            "prior_freeze_sha256": hashlib.sha256(PRIOR_FREEZE.read_bytes()).hexdigest(),
            "implementation_sha256": implementation_sha256(), "repositories": entries}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", action="append", required=True, help="name=/absolute/path")
    parser.add_argument("--out", type=Path, default=HERE / "rounds/round-00-freeze",
                        help="New, non-existing round directory")
    args = parser.parse_args()
    roots = {}
    for value in args.repo:
        name, sep, path = value.partition("=")
        if not sep or name in roots:
            parser.error("Use unique name=/absolute/path repository arguments")
        roots[name] = Path(path).resolve(strict=True)
    value = freeze(json.loads(CONFIG.read_text()), roots)
    summary = {"targets": sum(len(repo["targets"]) for repo in value["repositories"]),
               "requests": sum(item["request_sha256"] is not None
                               for repo in value["repositories"] for item in repo["targets"]),
               "structural_targets": sum(bool(item["structural_tests"])
                                         for repo in value["repositories"] for item in repo["targets"]),
               "tests": {repo["name"]: len(repo["test_ids"]) for repo in value["repositories"]}}
    with staged_round(args.out) as stage:
        (stage / "freeze.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        (stage / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
