"""Freeze and run the execution-blinded multi-repository relationship study."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT))

from benchmarks.archive import staged_round
from jev_map.enrich import make_request, proposals
from jev_map.index import build, digest
from jev_map.provider import JevClient, ProviderError, validate_response


def read(path: Path):
    return json.loads(path.read_text())


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def repository_arguments(values: list[str]) -> dict[str, Path]:
    result = {}
    for value in values:
        name, separator, path = value.partition("=")
        if not separator or not name or name in result:
            raise ValueError("Use each --repo once as name=/absolute/path")
        result[name] = Path(path).resolve(strict=True)
    return result


def git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *arguments], text=True, timeout=30).strip()


def implementation_hash() -> str:
    files = [PROJECT / "src/jev_map/index.py", PROJECT / "src/jev_map/enrich.py",
             PROJECT / "src/jev_map/provider.py", Path(__file__), HERE / "profile_plugin.py"]
    return digest({path.relative_to(PROJECT).as_posix(): path.read_text() for path in files})


def under(path: str, roots: list[str]) -> bool:
    return any(path == root.rstrip("/") or path.startswith(root.rstrip("/") + "/")
               for root in roots)


def selected_rows(config: dict, repo: dict, data: dict):
    eligible = []
    for function, peers in proposals(data, config["candidate_limit"]):
        if not under(function["path"], repo["source_roots"]):
            continue
        if under(function["path"], repo["source_excludes"]):
            continue
        if len(peers) != config["candidate_limit"]:
            continue
        if not all(under(peer["path"], repo["test_paths"]) for peer in peers):
            continue
        eligible.append((function, peers))
    eligible.sort(key=lambda row: hashlib.sha256(
        f'{config["seed"]}\0{repo["name"]}\0{row[0]["id"]}'.encode()).hexdigest())
    count = config["functions_per_repository"]
    if len(eligible) < count:
        raise ValueError(f'{repo["name"]} has only {len(eligible)} eligible functions')
    return eligible[:count]


def verify_repositories(config: dict, roots: dict[str, Path]):
    expected = {repo["name"] for repo in config["repositories"]}
    if set(roots) != expected:
        raise ValueError(f"Expected repository paths for {sorted(expected)}")
    for repo in config["repositories"]:
        root = roots[repo["name"]]
        actual = git(root, "rev-parse", "HEAD")
        if actual != repo["commit"]:
            raise ValueError(f'{repo["name"]} is {actual}, expected {repo["commit"]}')
        if subprocess.run(["git", "-C", str(root), "diff", "--quiet", "HEAD", "--"],
                          timeout=30).returncode != 0:
            raise ValueError(f'{repo["name"]} has tracked source changes')
        untracked_python = git(root, "ls-files", "--others", "--exclude-standard", "--", "*.py")
        if untracked_python:
            raise ValueError(f'{repo["name"]} has untracked Python source')


def freeze(config: dict, roots: dict[str, Path]) -> dict:
    verify_repositories(config, roots)
    repositories = []
    for repo in config["repositories"]:
        root = roots[repo["name"]]
        data = build(root)
        selected = []
        for function, peers in selected_rows(config, repo, data):
            request = make_request(data, function, peers, config["model"])
            selected.append({
                "function": function["id"],
                "tests": [peer["id"] for peer in peers],
                "request_sha256": digest(request),
                "evidence_hashes": {symbol["id"]: symbol["file_sha256"] for symbol in [function, *peers]},
            })
        repositories.append({"name": repo["name"], "commit": repo["commit"],
                             "corpus_sha256": data["snapshot"], "file_hashes": data["files"],
                             "selected": selected})
    return {"schema": 1, "protocol_sha256": digest(config),
            "implementation_sha256": implementation_hash(), "repositories": repositories}


def reconstruct(config: dict, frozen: dict, roots: dict[str, Path]):
    verify_repositories(config, roots)
    if frozen.get("schema") != 1:
        raise ValueError("Unsupported freeze schema")
    if frozen["protocol_sha256"] != digest(config):
        raise ValueError("Protocol configuration changed after freeze")
    if frozen["implementation_sha256"] != implementation_hash():
        raise ValueError("Study implementation changed after freeze")
    result = {}
    frozen_repos = {repo["name"]: repo for repo in frozen["repositories"]}
    expected_names = {repo["name"] for repo in config["repositories"]}
    if set(frozen_repos) != expected_names or len(frozen_repos) != len(frozen["repositories"]):
        raise ValueError("Frozen repositories differ from protocol")
    request_hashes = set()
    for repo in config["repositories"]:
        data = build(roots[repo["name"]])
        expected = frozen_repos[repo["name"]]
        if expected.get("commit") != repo["commit"]:
            raise ValueError(f'{repo["name"]} frozen commit differs from protocol')
        if data["snapshot"] != expected["corpus_sha256"] or data["files"] != expected["file_hashes"]:
            raise ValueError(f'{repo["name"]} source differs from freeze')
        items = expected.get("selected")
        count = config["functions_per_repository"]
        if not isinstance(items, list) or len(items) != count:
            raise ValueError(f'{repo["name"]} freeze must contain exactly {count} functions')
        functions = [item.get("function") for item in items if isinstance(item, dict)]
        hashes = [item.get("request_sha256") for item in items if isinstance(item, dict)]
        if (len(functions) != count or any(not isinstance(value, str) for value in functions)
                or len(set(functions)) != count):
            raise ValueError(f'{repo["name"]} frozen functions must be unique')
        if (len(hashes) != count or any(not isinstance(value, str) for value in hashes)
                or len(set(hashes)) != count or request_hashes.intersection(hashes)):
            raise ValueError("Frozen request hashes must be globally unique")
        request_hashes.update(hashes)
        rows = {function["id"]: (function, peers) for function, peers in selected_rows(config, repo, data)}
        selected = []
        for item in items:
            if len(item.get("tests", [])) != config["candidate_limit"]:
                raise ValueError(f'Wrong candidate count for {item["function"]}')
            try:
                function, peers = rows[item["function"]]
            except KeyError as exc:
                raise ValueError(f'Unknown frozen function: {item["function"]}') from exc
            if [peer["id"] for peer in peers] != item["tests"]:
                raise ValueError(f'Candidate drift for {item["function"]}')
            request = make_request(data, function, peers, config["model"])
            if digest(request) != item["request_sha256"]:
                raise ValueError(f'Request drift for {item["function"]}')
            selected.append((item, request))
        result[repo["name"]] = {"config": repo, "data": data, "selected": selected}
    return result


def clean_environment(root: Path, repo: dict, profile_output: Path | None = None) -> dict[str, str]:
    sensitive = ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
    environment = {key: value for key, value in os.environ.items()
                   if not (key.upper().endswith("_KEY") or any(word in key.upper() for word in sensitive))}
    paths = [str(HERE)] + [str((root / path).resolve()) for path in repo["pythonpath"]]
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(paths + ([existing] if existing else []))
    if profile_output is not None:
        environment["JEV_MAP_PROFILE_ROOT"] = str(root)
        environment["JEV_MAP_PROFILE_OUTPUT"] = str(profile_output)
    return environment


def selector(test_id: str) -> str:
    path, separator, name = test_id.partition("::")
    if not separator or not path.endswith(".py") or not name:
        raise ValueError(f"Invalid test identifier: {test_id}")
    return path + "::" + name.replace(".", "::")


def run_command(command: list[str], root: Path, environment: dict, timeout: int) -> dict:
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=root, env=environment, text=True,
                                   capture_output=True, timeout=timeout)
        return {"returncode": completed.returncode, "timed_out": False,
                "stdout_tail": completed.stdout[-2000:], "stderr_tail": completed.stderr[-2000:],
                "wall_seconds": time.perf_counter() - started}
    except subprocess.TimeoutExpired as exc:
        return {"returncode": None, "timed_out": True,
                "stdout_tail": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
                "stderr_tail": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
                "wall_seconds": time.perf_counter() - started}


def wilson(successes: int, total: int) -> dict | None:
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return {"lower": center - margin, "upper": center + margin}


def counts(rows: list[dict]) -> dict:
    test_eligible = [row for row in rows if row["test_eligible"]]
    scored = [row for row in test_eligible if row["score"] is not None]
    accepted = [row for row in scored if row["accepted"]]
    observed = [row for row in scored if row["observed"]]
    accepted_observed = sum(row["observed"] for row in accepted)
    rejected_observed = sum(row["observed"] for row in scored if not row["accepted"])
    return {"candidate_pairs": len(rows), "test_eligible_pairs": len(test_eligible),
            "test_eligible_fraction": len(test_eligible) / len(rows) if rows else None,
            "scored_eligible_pairs": len(scored), "execution_observed_pairs": len(observed),
            "accepted_pairs": len(accepted), "accepted_observed": accepted_observed,
            "accepted_not_observed": len(accepted) - accepted_observed,
            "rejected_observed": rejected_observed,
            "accepted_observed_fraction": accepted_observed / len(accepted) if accepted else None,
            "accepted_observed_wilson_95": wilson(accepted_observed, len(accepted)),
            "observed_candidate_coverage": accepted_observed / len(observed) if observed else None}


def test_eligible(receipt: dict) -> bool:
    return (receipt["returncode"] == 0 and not receipt["timed_out"]
            and receipt["call_passed"])


def ineligible_reason(receipt: dict) -> str | None:
    if receipt["timed_out"]:
        return "timed_out"
    if receipt["returncode"] != 0:
        return "failed_or_unselected"
    if not receipt["call_passed"]:
        return "no_passing_call_phase"
    return None


def run_study(config: dict, frozen: dict, roots: dict[str, Path], output: Path, env_file: Path):
    reconstructed = reconstruct(config, frozen, roots)
    with staged_round(output) as staging:
        preflight = {}
        for name, item in reconstructed.items():
            repo = item["config"]
            command = [sys.executable, "-m", "pytest", "-q", *repo["test_paths"]]
            preflight[name] = run_command(command, roots[name], clean_environment(roots[name], repo),
                                          config["preflight_timeout_seconds"])
        write(staging / "preflight.json", preflight)
        if any(row["returncode"] != 0 for row in preflight.values()):
            raise RuntimeError("Repository preflight failed; staged round was not published")

        client = JevClient(env_file=env_file)
        provider_rows = []
        for name, item in reconstructed.items():
            for frozen_item, request in item["selected"]:
                receipt = {"repository": name, "request": request,
                           "request_sha256": frozen_item["request_sha256"], "status": "error"}
                started = time.perf_counter()
                try:
                    response = client(request)
                    scores = validate_response(request, response)
                    receipt.update(status="ok", response=response, response_sha256=digest(response), scores=scores)
                except ProviderError as exc:
                    receipt["error"] = str(exc)
                receipt["wall_seconds"] = time.perf_counter() - started
                provider_rows.append(receipt)
                write(staging / "provider" / f'{name}-{frozen_item["request_sha256"]}.json', receipt)
        write(staging / "phase-order.json", {"jev_complete_before_oracle": True,
                                             "provider_requests": len(provider_rows)})

        test_ids = {name: sorted({test for frozen_item, _ in item["selected"] for test in frozen_item["tests"]})
                    for name, item in reconstructed.items()}
        test_rows = {}
        for name, tests in test_ids.items():
            repo = reconstructed[name]["config"]
            for test_id in tests:
                key = digest([name, test_id])
                trace_path = staging / "oracle" / f"{name}-{key}-trace.json"
                command = [sys.executable, "-m", "pytest", "-q", selector(test_id), "-p", "profile_plugin"]
                receipt = run_command(command, roots[name], clean_environment(roots[name], repo, trace_path),
                                      config["test_timeout_seconds"])
                trace = read(trace_path) if trace_path.exists() else {
                    "observed": [], "pytest_exit": None, "reports": [],
                }
                call_passed = any(report["when"] == "call" and report["outcome"] == "passed"
                                  for report in trace.get("reports", []))
                receipt.update(repository=name, test=test_id, selector=selector(test_id),
                               observed=trace["observed"], profile_pytest_exit=trace["pytest_exit"],
                               reports=trace.get("reports", []), call_passed=call_passed)
                test_rows[(name, test_id)] = receipt
                write(staging / "oracle" / f"{name}-{key}.json", receipt)

        pairs = []
        provider_by_request = {(row["repository"], row["request_sha256"]): row for row in provider_rows}
        for name, item in reconstructed.items():
            for frozen_item, request in item["selected"]:
                provider = provider_by_request[(name, frozen_item["request_sha256"])]
                for index, test_id in enumerate(frozen_item["tests"]):
                    test = test_rows[(name, test_id)]
                    score = provider.get("scores", {}).get(f"b{index}")
                    pairs.append({"repository": name, "function": frozen_item["function"], "test": test_id,
                                  "request_sha256": frozen_item["request_sha256"], "score": score,
                                  "accepted": score is not None and score >= config["threshold"],
                                  "test_eligible": test_eligible(test),
                                  "observed": frozen_item["function"] in test["observed"]})
        per_repo = {name: counts([row for row in pairs if row["repository"] == name])
                    for name in reconstructed}
        pooled = counts(pairs)
        provider_errors = sum(row["status"] != "ok" for row in provider_rows)
        capability_supported = (provider_errors == 0
                                and (pooled["test_eligible_fraction"] or 0) >= 0.9
                                and all(per_repo[name]["accepted_observed"] >= 1 for name in per_repo)
                                and (pooled["accepted_observed_fraction"] or 0) >= 0.8
                                and (pooled["accepted_observed_wilson_95"] or {}).get("lower", 0) >= 0.65)
        usage = [row.get("response", {}).get("usage", {}).get("input_tokens")
                 for row in provider_rows if row["status"] == "ok"]
        ineligible_reasons = {reason: sum(ineligible_reason(row) == reason for row in test_rows.values())
                              for reason in ("timed_out", "failed_or_unselected", "no_passing_call_phase")}
        summary = {"repositories": len(reconstructed),
                   "selected_functions": sum(len(item["selected"]) for item in reconstructed.values()),
                   "candidate_pairs": len(pairs), "unique_tests": len(test_rows),
                   "provider_requests": len(provider_rows),
                   "provider_errors": provider_errors,
                   "known_input_tokens": sum(value for value in usage if type(value) is int),
                   "unknown_usage_requests": sum(type(value) is not int for value in usage),
                   "ineligible_tests": sum(ineligible_reasons.values()),
                   "ineligible_test_reasons": ineligible_reasons,
                   "pooled": pooled, "per_repository": per_repo,
                   "frozen_capability_rule_supported": capability_supported,
                   "limits": "Execution-blinded source-selected sample. Call observation is not assertion effectiveness; non-observation is not proof of irrelevance; no agent outcomes measured."}
        write(staging / "pairs.json", pairs)
        write(staging / "summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "run"))
    parser.add_argument("--config", type=Path, default=HERE / "repositories.json")
    parser.add_argument("--freeze", type=Path, default=HERE / "freeze.json")
    parser.add_argument("--repo", action="append", default=[], help="name=/absolute/path")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args(argv)
    config = read(args.config)
    roots = repository_arguments(args.repo)
    if args.command == "freeze":
        value = freeze(config, roots)
        write(args.freeze, value)
        print(json.dumps({"repositories": len(value["repositories"]),
                          "selected_functions": sum(len(repo["selected"]) for repo in value["repositories"]),
                          "candidate_pairs": sum(len(item["tests"]) for repo in value["repositories"] for item in repo["selected"])}, indent=2))
    else:
        if args.out is None or args.env_file is None:
            parser.error("run requires --out and --env-file")
        print(json.dumps(run_study(config, read(args.freeze), roots, args.out, args.env_file), indent=2))


if __name__ == "__main__":
    main()
