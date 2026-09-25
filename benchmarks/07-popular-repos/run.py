"""Run the frozen popular-repository replication of benchmark 05.

Differences from `benchmarks/toolbelt_study.py`: each repository runs its tests
with its own interpreter, declared pytest arguments, and timeouts; the
execution oracle runs one pytest process per test file with `popular_profile`
(see PROTOCOL.md); and the repository-improvement gate scales with the sample.
Methods, candidates, threshold, eligibility rules, and metrics are unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from benchmarks.archive import staged_round
from benchmarks.graphify_compare import GRAPHIFY_VERSION, graphify_environment, lexical_scores, portable_log
from benchmarks.toolbelt_study import (combine, command_result, edge_metrics, edge_precision_interval,
                                       equal_lexical, graphify_ranked_paths, method_metrics,
                                       oracle_by_source_test, paired_hit_interval, read,
                                       test_environment, write)
from jev_map.enrich import make_request, proposals
from jev_map.index import build, digest
from jev_map.provider import JevClient, ProviderError, validate_response

HERE = Path(__file__).resolve().parent
FROZEN = HERE / "rounds/round-00-freeze/freeze.json"
METHODS = ("graphify_lexical", "graphify_jev_lexical", "structural_lexical",
           "structural_jev_lexical", "lexical_only")


def load_freeze():
    spec = importlib.util.spec_from_file_location("popular_freeze", HERE / "freeze.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pytest_command(python: Path, repo: dict, *extra: str) -> list[str]:
    return [str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider",
            *repo["test_paths"], *repo.get("pytest_args", []), *extra]


def environment(root: Path, repo: dict, output: Path | None = None) -> dict[str, str]:
    """Benchmark 05's sanitized test environment, plus this study's plugins."""
    result = test_environment(root, repo, output)
    result["PYTHONPATH"] = os.pathsep.join([str(HERE), result["PYTHONPATH"]])
    # Keep Hypothesis's example database out of the checkout.
    result["HYPOTHESIS_STORAGE_DIRECTORY"] = str(Path(tempfile.gettempdir()) / "jev-map-07-hypothesis" / repo["name"])
    return result


def clean(repo: dict, root: Path) -> None:
    """Remove declared test leftovers; refuse anything git tracks."""
    for relative in repo.get("clean_paths", []):
        path = root / relative
        if not path.exists():
            continue
        tracked = subprocess.run(["git", "-C", str(root), "ls-files", "--", relative], text=True,
                                 capture_output=True, timeout=30, check=True).stdout.strip()
        if tracked:
            raise RuntimeError(f"Refusing to remove {relative} in {repo['name']}: git tracks files there")
        shutil.rmtree(path) if path.is_dir() else path.unlink()


def collect_files(python: Path, repo: dict, root: Path) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="jev-map-07-collect-") as scratch:
        listing = Path(scratch) / "nodeids.txt"
        env = environment(root, repo)
        env["JEV_MAP_COLLECT_OUTPUT"] = str(listing)
        result = subprocess.run(pytest_command(python, repo, "--collect-only", "-p", "popular_collect"),
                                cwd=root, env=env, text=True, capture_output=True,
                                timeout=repo["preflight_timeout_seconds"])
        if result.returncode or not listing.is_file():
            raise RuntimeError(f"Test collection failed for {repo['name']}; no round published")
        nodeids = listing.read_text().splitlines()
    files: list[str] = []
    for nodeid in nodeids:
        if (path := nodeid.split("::", 1)[0]) not in files:
            files.append(path)
    if not files:
        raise RuntimeError(f"No test files collected for {repo['name']}; no round published")
    return files


def profile_by_file(python: Path, repo: dict, root: Path) -> tuple[dict, dict]:
    """Run each collected test file in its own traced pytest process, in order."""
    started = time.perf_counter()
    files = collect_files(python, repo, root)
    runs, cases = [], {}
    with tempfile.TemporaryDirectory(prefix="jev-map-07-") as scratch:
        for index, path in enumerate(files):
            output = Path(scratch) / f"{index:05d}.json"
            clean(repo, root)
            command = [str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider", path,
                       *repo.get("pytest_args", []), "-p", "popular_profile"]
            result = command_result(command, root, environment(root, repo, output),
                                    repo["profile_file_timeout_seconds"])
            result.update(file=path, stdout_tail=result["stdout_tail"][-1500:],
                          stderr_tail=result["stderr_tail"][-1500:], pytest_exit=None)
            if output.is_file():
                raw = read(output)
                result["pytest_exit"] = raw["pytest_exit"]
                cases.update(raw["cases"])
            runs.append(result)
    clean(repo, root)
    complete = all(row["returncode"] == 0 and not row["timed_out"] for row in runs)
    merged = {"pytest_exit": 0 if complete else 1, "cases": cases}
    record = {"files": len(files), "complete": complete, "wall_seconds": time.perf_counter() - started,
              "failed_files": [row["file"] for row in runs if row["returncode"] != 0 or row["timed_out"]],
              "runs": runs}
    return merged, record


def interpreter_version(python: Path) -> str:
    return subprocess.check_output([str(python), "-c", "import sys; print(sys.version.split()[0])"],
                                   text=True, timeout=60).strip()


def run(roots: dict[str, Path], pythons: dict[str, Path], output: Path, env_file: Path) -> dict:
    run_started = time.perf_counter()
    freeze_module = load_freeze()
    config = read(freeze_module.CONFIG)
    frozen = read(FROZEN)
    names = [repo["name"] for repo in config["repositories"]]
    if set(pythons) != set(names):
        raise ValueError("Give exactly one --python per configured repository")
    if config["graphify_package"] != f"graphifyy=={GRAPHIFY_VERSION}":
        raise ValueError("Graphify adapter version differs from frozen configuration")
    if freeze_module.freeze(config, roots) != frozen:
        raise ValueError("Source, protocol, implementation, or frozen selection has changed")
    frozen_repos = {item["name"]: item for item in frozen["repositories"]}
    with staged_round(output) as stage:
        interpreters = {name: interpreter_version(pythons[name]) for name in names}
        preflight = {}
        for repo in config["repositories"]:
            name = repo["name"]
            clean(repo, roots[name])
            preflight[name] = command_result(pytest_command(pythons[name], repo), roots[name],
                                             environment(roots[name], repo),
                                             repo["preflight_timeout_seconds"])
        for repo in config["repositories"]:
            clean(repo, roots[repo["name"]])
        write(stage / "preflight.json", preflight)
        if any(row["returncode"] != 0 for row in preflight.values()):
            raise RuntimeError("Repository preflight failed; no round published")

        indexed = {}
        for name in names:
            started = time.perf_counter()
            data = build(roots[name])
            indexed[name] = {"data": data, "wall_seconds": time.perf_counter() - started}
        graphify = {}
        for name in names:
            target = stage / "graphify" / name
            command = ["uvx", "--from", config["graphify_package"], "graphify", "extract",
                       str(roots[name]), "--code-only", "--no-cluster", "--max-workers", "2",
                       "--out", str(target)]
            started = time.perf_counter()
            result = subprocess.run(command, text=True, capture_output=True,
                                    timeout=config["graphify_timeout_seconds"],
                                    env=graphify_environment(os.environ))
            elapsed = time.perf_counter() - started
            write(stage / "graphify-logs" / f"{name}.json",
                  {"command": [portable_log(part, roots[name], stage) for part in command],
                   "returncode": result.returncode, "wall_seconds": elapsed,
                   "stdout": portable_log(result.stdout, roots[name], stage),
                   "stderr": portable_log(result.stderr, roots[name], stage)})
            if result.returncode:
                raise RuntimeError(f"Graphify failed on {name}; no round published")
            graph_path = target / "graphify-out/graph.json"
            graphify[name] = {"graph": read(graph_path), "wall_seconds": elapsed,
                             "sha256": hashlib.sha256(graph_path.read_bytes()).hexdigest()}

        client = JevClient(env_file=env_file)
        provider = {}
        for name in names:
            data = indexed[name]["data"]
            candidates = {function["id"]: peers for function, peers in
                          proposals(data, config["candidate_limit"])}
            for target in frozen_repos[name]["targets"]:
                if target["request_sha256"] is None:
                    continue
                function = data["symbols"][target["function"]]
                request = make_request(data, function, candidates.get(function["id"], []), config["model"])
                if digest(request) != target["request_sha256"]:
                    raise ValueError(f"Frozen Jev request changed for {function['id']}")
                receipt = {"repository": name, "function": function["id"], "request": request,
                           "request_sha256": digest(request), "status": "error"}
                started = time.perf_counter()
                try:
                    response = client(request)
                    receipt.update(status="ok", response=response, response_sha256=digest(response),
                                   scores=validate_response(request, response))
                except ProviderError as exc:
                    receipt["error"] = str(exc)
                receipt["wall_seconds"] = time.perf_counter() - started
                provider[name, function["id"]] = receipt
                write(stage / "provider" / f"{name}-{digest(request)}.json", receipt)
        write(stage / "phase-order.json", {"maps_and_jev_complete_before_oracle": True,
                                           "provider_requests": len(provider)})

        # Repositories profile in parallel; files within one checkout run in order.
        with ThreadPoolExecutor(max_workers=len(names)) as pool:
            profiled = dict(zip(names, pool.map(
                lambda repo: profile_by_file(pythons[repo["name"]], repo, roots[repo["name"]]),
                config["repositories"])))
        oracle, oracle_stats, profile_runs = {}, {}, {}
        for name in names:
            raw, profile_runs[name] = profiled[name]
            write(stage / "oracle" / f"{name}.json", raw)
            oracle[name], oracle_stats[name] = oracle_by_source_test(raw, frozen_repos[name]["test_ids"])
            write(stage / "oracle" / f"{name}-aggregate.json", oracle[name])
        write(stage / "profile-runs.json", profile_runs)
        oracle_complete = all(row["complete"] for row in profile_runs.values())

        rankings, candidate_pairs, graph_coverage = [], [], {}
        for name in names:
            data = indexed[name]["data"]
            tests = frozen_repos[name]["test_ids"]
            graph = graphify[name]["graph"]
            graph_coverage[name] = []
            lexical = lexical_scores(data, [{"function": item["function"], "test": test}
                                            for item in frozen_repos[name]["targets"] for test in tests])
            structural = defaultdict(list)
            for link in data["links"]:
                if link["evidence"] == "structural" and link["test"] in oracle[name]:
                    structural[link["function"]].append(link)
            for item in frozen_repos[name]["targets"]:
                function = item["function"]
                graph_paths, coverage = graphify_ranked_paths(graph, function, tests)
                graph_coverage[name].append(coverage)
                structural_links = sorted(structural[function], key=lambda row: (len(row["call_path"]), row["test"]))
                lexical_tests = sorted(tests, key=lambda test: (-lexical[function, test], test))
                scores = provider.get((name, function), {}).get("scores", {})
                jev_candidates = [{"test": test, "score": scores.get(f"b{index}")}
                                  for index, test in enumerate(item["candidates"])]
                accepted_tests = [row["test"] for row in sorted(
                    (row for row in jev_candidates if row["score"] is not None
                     and row["score"] >= config["jev_threshold"]), key=lambda row: (-row["score"], row["test"]))]
                graph_tests = [row["test"] for row in graph_paths]
                structural_tests = [row["test"] for row in structural_links]
                methods = {
                    "graphify_lexical": combine(("graphify", graph_tests), ("lexical", lexical_tests)),
                    "graphify_jev_lexical": combine(("graphify", graph_tests), ("jev", accepted_tests),
                                                    ("lexical", lexical_tests)),
                    "structural_lexical": combine(("structural", structural_tests), ("lexical", lexical_tests)),
                    "structural_jev_lexical": combine(("structural", structural_tests), ("jev", accepted_tests),
                                                      ("lexical", lexical_tests)),
                    "lexical_only": combine(("lexical", lexical_tests)),
                }
                observed_tests = sorted(test for test in tests if oracle[name][test]["eligible"]
                                        and function in oracle[name][test]["observed"])
                for selected in methods.values():
                    for prediction in selected:
                        row = oracle[name][prediction["test"]]
                        prediction["observed"] = function in row["observed"] if row["eligible"] else None
                graph_by_test = {row["test"] for row in graph_paths}
                rankings.append({"repository": name, "function": function, "observed_tests": observed_tests,
                                 "methods": methods, "graphify_links": graph_paths,
                                 "structural_links": structural_links, "jev_candidates": jev_candidates,
                                 "lexical_top_three": lexical_tests[:3]})
                for candidate in jev_candidates:
                    test = candidate["test"]
                    row = oracle[name][test]
                    candidate_pairs.append({"repository": name, "function": function, "test": test,
                                            "jev_score": candidate["score"],
                                            "jev_accepted": test in accepted_tests,
                                            "lexical_score": lexical[function, test],
                                            "graphify_link": test in graph_by_test,
                                            "test_eligible": row["eligible"],
                                            "observed": function in row["observed"] if row["eligible"] else None})

        methods = {method: method_metrics(rankings, method) for method in METHODS}
        per_repo = {name: {method: method_metrics([row for row in rankings if row["repository"] == name], method)
                           for method in METHODS} for name in names}
        base, treatment = methods["graphify_lexical"]["hit_at_1"], methods["graphify_jev_lexical"]["hit_at_1"]
        delta = treatment - base if base is not None and treatment is not None else None
        primary_interval = paired_hit_interval(rankings, config, "graphify_lexical", "graphify_jev_lexical")
        improved = sum(per_repo[name]["graphify_jev_lexical"]["hit_at_1"] > per_repo[name]["graphify_lexical"]["hit_at_1"]
                       for name in names if per_repo[name]["graphify_lexical"]["hit_at_1"] is not None)
        provider_ok = all(row["status"] == "ok" for row in provider.values())
        primary_supported = (oracle_complete and provider_ok and delta is not None and delta >= 0.05
                             and primary_interval.get("lower_95", -1) > 0
                             and improved >= config["min_repositories_improved"])
        accepted_set = {(row["repository"], row["function"], row["test"])
                        for row in candidate_pairs if row["test_eligible"] and row["jev_accepted"]}
        accepted_metrics = edge_metrics(candidate_pairs, accepted_set)
        lexical_metrics = edge_metrics(candidate_pairs, equal_lexical(candidate_pairs, len(accepted_set)))
        edge_delta = ((accepted_metrics["observed_fraction"] or 0)
                      - (lexical_metrics["observed_fraction"] or 0)) if accepted_set else None
        edge_interval = edge_precision_interval(candidate_pairs, config)
        edge_supported = (oracle_complete and provider_ok and edge_delta is not None and edge_delta >= 0.05
                          and edge_interval.get("lower_95", -1) > 0)
        usage = [row.get("response", {}).get("usage", {}).get("input_tokens")
                 for row in provider.values() if row["status"] == "ok"]
        summary = {
            "kind": "popular_repository_replication", "repositories": len(names),
            "targets": len(rankings), "candidate_pairs": len(candidate_pairs),
            "frozen_sha256": hashlib.sha256(FROZEN.read_bytes()).hexdigest(),
            "interpreters": interpreters, "oracle": oracle_stats, "oracle_complete": oracle_complete,
            "profile_runs": {name: {key: value for key, value in row.items() if key != "runs"}
                             for name, row in profile_runs.items()},
            "graphify": {name: {"wall_seconds": row["wall_seconds"], "sha256": row["sha256"],
                                "nodes": len(row["graph"]["nodes"]), "edges": len(row["graph"]["edges"]),
                                "input_tokens": row["graph"].get("input_tokens"),
                                "output_tokens": row["graph"].get("output_tokens"),
                                "function_nodes_mapped": sum(item["function_mapped"] for item in graph_coverage[name]),
                                "test_nodes_mapped": graph_coverage[name][0]["tests_mapped"]}
                         for name, row in graphify.items()},
            "local_index_wall_seconds": {name: row["wall_seconds"] for name, row in indexed.items()},
            "provider_requests": len(provider),
            "provider_errors": sum(row["status"] != "ok" for row in provider.values()),
            "provider_wall_seconds_sum": sum(row["wall_seconds"] for row in provider.values()),
            "known_input_tokens": sum(value for value in usage if type(value) is int),
            "unknown_usage_requests": sum(type(value) is not int for value in usage),
            "methods": methods, "per_repository": per_repo,
            "primary": {"contrast": "graphify_jev_lexical - graphify_lexical hit_at_1", "delta": delta,
                        "bootstrap": primary_interval, "repositories_improved": improved,
                        "frozen_gate_supported": primary_supported},
            "edge_filter": {"jev": accepted_metrics, "lexical_equal_count": lexical_metrics,
                            "precision_delta": edge_delta, "bootstrap": edge_interval,
                            "frozen_gate_supported": edge_supported},
            "limits": "Execution observation is not assertion effectiveness. Offline test subsets as declared in "
                      "repositories.json. No complete coding-agent outcomes or dollar cost.",
            "total_runner_wall_seconds": time.perf_counter() - run_started,
        }
        write(stage / "rankings.json", rankings)
        write(stage / "candidate-pairs.json", candidate_pairs)
        write(stage / "summary.json", summary)
    return summary


def pairs(parser: argparse.ArgumentParser, values: list[str], label: str) -> dict[str, Path]:
    result = {}
    for value in values:
        name, sep, path = value.partition("=")
        if not sep or name in result:
            parser.error(f"Use unique name=/absolute/path {label} arguments")
        result[name] = Path(path).absolute()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", action="append", required=True, help="name=/absolute/root")
    parser.add_argument("--python", action="append", required=True, help="name=/absolute/venv/bin/python")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    roots = {name: path.resolve(strict=True) for name, path in pairs(parser, args.repo, "--repo").items()}
    summary = run(roots, pairs(parser, args.python, "--python"), args.out, args.env_file)
    print(json.dumps({key: summary[key] for key in ("targets", "provider_errors", "primary", "edge_filter")},
                     indent=2))


if __name__ == "__main__":
    main()
