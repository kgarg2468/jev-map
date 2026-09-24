"""Run the frozen Graphify + Jev test-finding comparison on full test suites."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import os
import random
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

from benchmarks.archive import staged_round
from benchmarks.graphify_compare import (GRAPHIFY_VERSION, graph_node, graphify_environment,
                                         lexical_scores, portable_log)
from benchmarks.heldout_freeze import CONFIG, HERE, freeze
from jev_map.enrich import make_request, proposals
from jev_map.index import build, digest
from jev_map.provider import JevClient, ProviderError, validate_response

PROJECT = Path(__file__).resolve().parents[1]
FROZEN = HERE / "rounds/round-00-freeze/freeze.json"
CALL_RELATIONS = frozenset({"calls", "indirect_call"})


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def read(path: Path):
    return json.loads(path.read_text())


def test_environment(root: Path, repo: dict, output: Path | None = None) -> dict[str, str]:
    sensitive = ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
    environment = {key: value for key, value in os.environ.items()
                   if not (key.upper().endswith("_KEY") or any(word in key.upper() for word in sensitive))}
    paths = [str(PROJECT / "benchmarks")] + [str((root / path).resolve()) for path in repo["pythonpath"]]
    old_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(paths + ([old_path] if old_path else []))
    if output is not None:
        environment["JEV_MAP_PROFILE_ROOT"] = str(root)
        environment["JEV_MAP_PROFILE_OUTPUT"] = str(output)
    return environment


def command_result(command: list[str], root: Path, environment: dict[str, str], timeout: int) -> dict:
    started = time.perf_counter()
    try:
        result = subprocess.run(command, cwd=root, env=environment, text=True,
                                capture_output=True, timeout=timeout)
        return {"returncode": result.returncode, "timed_out": False,
                "stdout_tail": result.stdout[-4000:], "stderr_tail": result.stderr[-4000:],
                "wall_seconds": time.perf_counter() - started}
    except subprocess.TimeoutExpired as exc:
        return {"returncode": None, "timed_out": True,
                "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
                "stderr_tail": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
                "wall_seconds": time.perf_counter() - started}


def graphify_ranked_paths(graph: dict, function: str, tests: list[str]) -> tuple[list[dict], dict]:
    """Shortest directed call paths, preferring fewer inferred edges."""
    target = graph_node(graph, function)
    test_nodes = {test: graph_node(graph, test) for test in tests}
    coverage = {"function_mapped": target is not None,
                "tests_mapped": sum(node is not None for node in test_nodes.values()),
                "tests_total": len(tests)}
    if target is None:
        return [], coverage
    reverse: dict[str, list[dict]] = defaultdict(list)
    for edge in graph["edges"]:
        if edge["relation"] in CALL_RELATIONS:
            reverse[edge["target"]].append(edge)
    best = {target: (0, 0)}
    next_edge = {}
    heap = [(0, 0, target)]
    while heap:
        indirect, length, node = heapq.heappop(heap)
        if (indirect, length) != best[node]:
            continue
        for edge in reverse[node]:
            predecessor = edge["source"]
            candidate = (indirect + int(edge.get("confidence") != "EXTRACTED"), length + 1)
            if predecessor not in best or candidate < best[predecessor]:
                best[predecessor] = candidate
                next_edge[predecessor] = edge
                heapq.heappush(heap, (*candidate, predecessor))
    ranked = []
    for test, start in test_nodes.items():
        if start is None or start not in best or start == target:
            continue
        path = []
        current = start
        while current != target:
            edge = next_edge[current]
            path.append({key: edge[key] for key in ("source", "target", "relation", "confidence")})
            current = edge["target"]
        ranked.append({"test": test, "inferred_edges": best[start][0],
                       "length": best[start][1], "path": path})
    ranked.sort(key=lambda row: (row["inferred_edges"], row["length"], row["test"]))
    return ranked, coverage


def combine(*sources: tuple[str, list[str]], limit: int = 3) -> list[dict]:
    result = []
    seen = set()
    for source, tests in sources:
        for test in tests:
            if test not in seen:
                result.append({"test": test, "source": source})
                seen.add(test)
                if len(result) == limit:
                    return result
    return result


def oracle_by_source_test(raw: dict, test_ids: list[str]) -> tuple[dict[str, dict], dict]:
    """Combine parameterized cases; uncollected/skipped source tests stay unknown."""
    by_selector = {path + "::" + name.replace(".", "::"): symbol
                   for symbol in test_ids for path, _, name in [symbol.partition("::")]}
    variants: dict[str, list[dict]] = defaultdict(list)
    unrecognized = []
    for nodeid, case in raw["cases"].items():
        base = nodeid.partition("[")[0]
        symbol = by_selector.get(base)
        if symbol is None:
            # Pytest may report paths relative to an ancestor rootdir even when
            # the frozen symbol path is relative to the checkout itself.
            suffixes = [value for selector, value in by_selector.items()
                        if base.endswith("/" + selector)]
            if len(suffixes) == 1:
                symbol = suffixes[0]
        if symbol is None:
            unrecognized.append(nodeid)
        else:
            variants[symbol].append(case)
    aggregate = {}
    for symbol in test_ids:
        cases = variants[symbol]
        call_passed = bool(cases) and all(any(
            report["when"] == "call" and report["outcome"] == "passed"
            for report in case.get("reports", [])) for case in cases)
        threaded = any(case.get("threaded", False) for case in cases)
        thread_unknown = any(case.get("thread_coverage_unknown", False) for case in cases)
        eligible = call_passed and not thread_unknown
        observed = sorted({function for case in cases for function in case["observed"]})
        aggregate[symbol] = {"eligible": eligible, "variants": len(cases),
                             "threaded": threaded,
                             "observed": observed if eligible else [],
                             "reason": (None if eligible else "thread_coverage_unknown" if thread_unknown
                                        else "uncollected_or_no_passing_call")}
    stats = {"source_tests": len(test_ids), "eligible": sum(row["eligible"] for row in aggregate.values()),
             "uncollected": sum(row["variants"] == 0 for row in aggregate.values()),
             "threaded": sum(row["threaded"] for row in aggregate.values()),
             "thread_coverage_unknown": sum(row["reason"] == "thread_coverage_unknown"
                                            for row in aggregate.values()),
             "collected_but_ineligible": sum(row["variants"] > 0 and not row["eligible"]
                                         for row in aggregate.values()),
             "unrecognized_collected_cases": len(unrecognized),
             "unrecognized_examples": unrecognized[:10]}
    return aggregate, stats


def method_metrics(rows: list[dict], method: str) -> dict:
    positives = [row for row in rows if row["observed_tests"]]
    first_hits = sum(row["methods"][method][0]["observed"] is True for row in positives
                     if row["methods"][method])
    top_three = sum(any(item["observed"] is True for item in row["methods"][method])
                    for row in positives)
    reciprocal_rank = sum(next((1 / index for index, item in
                                enumerate(row["methods"][method], 1) if item["observed"] is True), 0)
                          for row in positives)
    zero_positive = [row for row in rows if not row["observed_tests"]]
    invalid = sum(item["observed"] is None for row in rows for item in row["methods"][method])
    return {"positive_targets": len(positives), "hit_at_1": first_hits / len(positives) if positives else None,
            "hit_at_1_count": first_hits, "hit_at_3": top_three / len(positives) if positives else None,
            "hit_at_3_count": top_three, "mean_reciprocal_rank": reciprocal_rank / len(positives)
            if positives else None, "zero_observed_targets": len(zero_positive),
            "suggestions_on_zero_observed_targets": sum(len(row["methods"][method]) for row in zero_positive),
            "ineligible_suggestions": invalid}


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def paired_hit_interval(rows: list[dict], config: dict, baseline: str, treatment: str) -> dict:
    groups = {name: [row for row in rows if row["repository"] == name]
              for name in {row["repository"] for row in rows}}
    seed = int(hashlib.sha256(config["bootstrap_seed"].encode()).hexdigest(), 16)
    generator = random.Random(seed)
    differences = []
    for _ in range(config["bootstrap_resamples"]):
        sample = [generator.choice(group) for name, group in sorted(groups.items())
                  for _ in range(len(group))]
        positive = [row for row in sample if row["observed_tests"]]
        if not positive:
            continue
        base = sum(row["methods"][baseline][0]["observed"] is True for row in positive
                   if row["methods"][baseline])
        improved = sum(row["methods"][treatment][0]["observed"] is True for row in positive
                       if row["methods"][treatment])
        differences.append((improved - base) / len(positive))
    return {"resamples": len(differences), "lower_95": percentile(differences, 0.025),
            "upper_95": percentile(differences, 0.975)} if differences else {"resamples": 0}


def edge_metrics(pairs: list[dict], selected: set[tuple[str, str, str]]) -> dict:
    eligible = [row for row in pairs if row["test_eligible"]]
    emitted = [row for row in eligible if (row["repository"], row["function"], row["test"]) in selected]
    true_positive = sum(row["observed"] for row in emitted)
    return {"emitted_eligible": len(emitted), "observed": true_positive,
            "not_observed": len(emitted) - true_positive,
            "observed_fraction": true_positive / len(emitted) if emitted else None,
            "ineligible_selected": len(selected) - len(emitted)}


def equal_lexical(pairs: list[dict], count: int) -> set[tuple[str, str, str]]:
    eligible = [row for row in pairs if row["test_eligible"]]
    eligible.sort(key=lambda row: (-row["lexical_score"], row["repository"],
                                   row["function"], row["test"]))
    return {(row["repository"], row["function"], row["test"]) for row in eligible[:count]}


def edge_precision_interval(pairs: list[dict], config: dict) -> dict:
    by_target = defaultdict(list)
    for row in pairs:
        by_target[row["repository"], row["function"]].append(row)
    groups = defaultdict(list)
    for (repository, _), target_pairs in by_target.items():
        groups[repository].append(target_pairs)
    seed = int(hashlib.sha256((config["bootstrap_seed"] + "-edges").encode()).hexdigest(), 16)
    generator = random.Random(seed)
    differences = []
    for _ in range(config["bootstrap_resamples"]):
        sampled = [row for name, group in sorted(groups.items()) for _ in range(len(group))
                   for row in generator.choice(group)]
        accepted = [row for row in sampled if row["test_eligible"] and row["jev_accepted"]]
        if not accepted:
            continue
        lexical = sorted((row for row in sampled if row["test_eligible"]),
                         key=lambda row: (-row["lexical_score"], row["repository"],
                                          row["function"], row["test"]))[:len(accepted)]
        differences.append(sum(row["observed"] for row in accepted) / len(accepted)
                           - sum(row["observed"] for row in lexical) / len(lexical))
    return {"resamples": len(differences), "lower_95": percentile(differences, 0.025),
            "upper_95": percentile(differences, 0.975)} if differences else {"resamples": 0}


def run(roots: dict[str, Path], output: Path, env_file: Path) -> dict:
    run_started = time.perf_counter()
    config = read(CONFIG)
    frozen = read(FROZEN)
    if config["graphify_package"] != f"graphifyy=={GRAPHIFY_VERSION}":
        raise ValueError("Graphify adapter version differs from frozen configuration")
    if freeze(config, roots) != frozen:
        raise ValueError("Source, protocol, implementation, or frozen selection has changed")
    with staged_round(output) as stage:
        preflight = {}
        for repo in config["repositories"]:
            name = repo["name"]
            command = [sys.executable, "-m", "pytest", "-q", *repo["test_paths"]]
            preflight[name] = command_result(command, roots[name],
                                             test_environment(roots[name], repo), 300)
        write(stage / "preflight.json", preflight)
        if any(row["returncode"] != 0 for row in preflight.values()):
            raise RuntimeError("Repository preflight failed; no round published")

        indexed = {}
        for repo in config["repositories"]:
            name = repo["name"]
            started = time.perf_counter()
            data = build(roots[name])
            indexed[name] = {"data": data, "wall_seconds": time.perf_counter() - started}
        graphify = {}
        for repo in config["repositories"]:
            name = repo["name"]
            target = stage / "graphify" / name
            command = ["uvx", "--from", config["graphify_package"], "graphify", "extract",
                       str(roots[name]), "--code-only", "--no-cluster", "--max-workers", "2",
                       "--out", str(target)]
            started = time.perf_counter()
            result = subprocess.run(command, text=True, capture_output=True, timeout=300,
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
        for repo in config["repositories"]:
            name = repo["name"]
            data = indexed[name]["data"]
            candidates = {function["id"]: peers for function, peers in
                          proposals(data, config["candidate_limit"])}
            for target in next(item for item in frozen["repositories"] if item["name"] == name)["targets"]:
                function = data["symbols"][target["function"]]
                peers = candidates.get(function["id"], [])
                request = make_request(data, function, peers, config["model"])
                if digest(request) != target["request_sha256"]:
                    raise ValueError(f"Frozen Jev request changed for {function['id']}")
                receipt = {"repository": name, "function": function["id"], "request": request,
                           "request_sha256": digest(request), "status": "error"}
                started = time.perf_counter()
                try:
                    response = client(request)
                    receipt.update(status="ok", response=response,
                                   response_sha256=digest(response),
                                   scores=validate_response(request, response))
                except ProviderError as exc:
                    receipt["error"] = str(exc)
                receipt["wall_seconds"] = time.perf_counter() - started
                provider[name, function["id"]] = receipt
                write(stage / "provider" / f"{name}-{digest(request)}.json", receipt)
        write(stage / "phase-order.json", {"maps_and_jev_complete_before_oracle": True,
                                           "provider_requests": len(provider)})

        oracle = {}
        oracle_stats = {}
        profile_runs = {}
        for repo in config["repositories"]:
            name = repo["name"]
            output_path = stage / "oracle" / f"{name}.json"
            command = [sys.executable, "-m", "pytest", "-q", *repo["test_paths"],
                       "-p", "full_suite_profile"]
            profile_runs[name] = command_result(command, roots[name],
                                                 test_environment(roots[name], repo, output_path), 900)
            if not output_path.is_file():
                raise RuntimeError(f"No profiler output for {name}; no round published")
            raw = read(output_path)
            test_ids = next(item for item in frozen["repositories"] if item["name"] == name)["test_ids"]
            oracle[name], oracle_stats[name] = oracle_by_source_test(raw, test_ids)
            write(stage / "oracle" / f"{name}-aggregate.json", oracle[name])
        write(stage / "profile-runs.json", profile_runs)
        oracle_complete = all(row["returncode"] == 0 and not row["timed_out"]
                              for row in profile_runs.values())

        rankings = []
        candidate_pairs = []
        graph_coverage = {}
        for repo in config["repositories"]:
            name = repo["name"]
            data = indexed[name]["data"]
            frozen_repo = next(item for item in frozen["repositories"] if item["name"] == name)
            tests = frozen_repo["test_ids"]
            graph = graphify[name]["graph"]
            graph_coverage[name] = []
            lexical_rows = [{"function": item["function"], "test": test}
                            for item in frozen_repo["targets"] for test in tests]
            lexical = lexical_scores(data, lexical_rows)
            structural = defaultdict(list)
            for link in data["links"]:
                if link["evidence"] == "structural" and link["test"] in oracle[name]:
                    structural[link["function"]].append(link)
            for item in frozen_repo["targets"]:
                function = item["function"]
                graph_paths, coverage = graphify_ranked_paths(graph, function, tests)
                graph_coverage[name].append(coverage)
                graph_tests = [row["test"] for row in graph_paths]
                structural_links = sorted(structural[function],
                                          key=lambda row: (len(row["call_path"]), row["test"]))
                structural_tests = [row["test"] for row in structural_links]
                lexical_tests = sorted(tests, key=lambda test: (-lexical[function, test], test))
                receipt = provider[name, function]
                scores = receipt.get("scores", {})
                jev_candidates = [{"test": test, "score": scores.get(f"b{index}")}
                                  for index, test in enumerate(item["candidates"])]
                accepted = sorted((row for row in jev_candidates if row["score"] is not None
                                   and row["score"] >= config["jev_threshold"]),
                                  key=lambda row: (-row["score"], row["test"]))
                accepted_tests = [row["test"] for row in accepted]
                methods = {
                    "graphify_lexical": combine(("graphify", graph_tests), ("lexical", lexical_tests)),
                    "graphify_jev_lexical": combine(("graphify", graph_tests),
                                                    ("jev", accepted_tests), ("lexical", lexical_tests)),
                    "structural_lexical": combine(("structural", structural_tests),
                                                  ("lexical", lexical_tests)),
                    "structural_jev_lexical": combine(("structural", structural_tests),
                                                      ("jev", accepted_tests), ("lexical", lexical_tests)),
                    "lexical_only": combine(("lexical", lexical_tests)),
                }
                observed_tests = sorted(test for test in tests if oracle[name][test]["eligible"]
                                        and function in oracle[name][test]["observed"])
                for selected in methods.values():
                    for prediction in selected:
                        test = prediction["test"]
                        prediction["observed"] = (function in oracle[name][test]["observed"]
                                                  if oracle[name][test]["eligible"] else None)
                graph_paths_by_test = {row["test"]: row for row in graph_paths}
                rankings.append({"repository": name, "function": function,
                                 "observed_tests": observed_tests, "methods": methods,
                                 "graphify_links": graph_paths,
                                 "structural_links": structural_links,
                                 "jev_candidates": jev_candidates,
                                 "lexical_top_three": lexical_tests[:3]})
                for candidate in jev_candidates:
                    test = candidate["test"]
                    candidate_pairs.append({"repository": name, "function": function, "test": test,
                                            "jev_score": candidate["score"],
                                            "jev_accepted": test in accepted_tests,
                                            "lexical_score": lexical[function, test],
                                            "graphify_link": test in graph_paths_by_test,
                                            "test_eligible": oracle[name][test]["eligible"],
                                            "observed": function in oracle[name][test]["observed"]
                                            if oracle[name][test]["eligible"] else None})

        method_names = ("graphify_lexical", "graphify_jev_lexical", "structural_lexical",
                        "structural_jev_lexical", "lexical_only")
        methods = {method: method_metrics(rankings, method) for method in method_names}
        per_repo = {repo["name"]: {method: method_metrics(
            [row for row in rankings if row["repository"] == repo["name"]], method)
            for method in method_names} for repo in config["repositories"]}
        base = methods["graphify_lexical"]["hit_at_1"]
        treatment = methods["graphify_jev_lexical"]["hit_at_1"]
        delta = treatment - base if base is not None and treatment is not None else None
        primary_interval = paired_hit_interval(rankings, config, "graphify_lexical",
                                               "graphify_jev_lexical")
        repo_improvements = sum(
            per_repo[name]["graphify_jev_lexical"]["hit_at_1"]
            > per_repo[name]["graphify_lexical"]["hit_at_1"]
            for name in per_repo if per_repo[name]["graphify_lexical"]["hit_at_1"] is not None)
        primary_supported = (oracle_complete and delta is not None and delta >= 0.05
                             and primary_interval.get("lower_95", -1) > 0
                             and repo_improvements >= 2)
        accepted_set = {(row["repository"], row["function"], row["test"])
                        for row in candidate_pairs if row["test_eligible"] and row["jev_accepted"]}
        lexical_set = equal_lexical(candidate_pairs, len(accepted_set))
        accepted_metrics = edge_metrics(candidate_pairs, accepted_set)
        lexical_metrics = edge_metrics(candidate_pairs, lexical_set)
        edge_delta = ((accepted_metrics["observed_fraction"] or 0)
                      - (lexical_metrics["observed_fraction"] or 0)) if accepted_set else None
        edge_interval = edge_precision_interval(candidate_pairs, config)
        edge_supported = (oracle_complete and edge_delta is not None and edge_delta >= 0.05
                          and edge_interval.get("lower_95", -1) > 0)
        provider_rows = list(provider.values())
        usage = [row.get("response", {}).get("usage", {}).get("input_tokens")
                 for row in provider_rows if row["status"] == "ok"]
        summary = {
            "kind": "prospective_heldout_toolbelt", "repositories": len(config["repositories"]),
            "targets": len(rankings), "candidate_pairs": len(candidate_pairs),
            "frozen_sha256": hashlib.sha256(FROZEN.read_bytes()).hexdigest(),
            "oracle": oracle_stats, "oracle_complete": oracle_complete,
            "profile_runs": profile_runs,
            "graphify": {name: {"wall_seconds": row["wall_seconds"], "sha256": row["sha256"],
                                "nodes": len(row["graph"]["nodes"]), "edges": len(row["graph"]["edges"]),
                                "input_tokens": row["graph"].get("input_tokens"),
                                "output_tokens": row["graph"].get("output_tokens"),
                                "function_nodes_mapped": sum(item["function_mapped"] for item in graph_coverage[name]),
                                "test_nodes_mapped": graph_coverage[name][0]["tests_mapped"]}
                         for name, row in graphify.items()},
            "local_index_wall_seconds": {name: row["wall_seconds"] for name, row in indexed.items()},
            "provider_requests": len(provider_rows),
            "provider_errors": sum(row["status"] != "ok" for row in provider_rows),
            "provider_wall_seconds_sum": sum(row["wall_seconds"] for row in provider_rows),
            "known_input_tokens": sum(value for value in usage if type(value) is int),
            "unknown_usage_requests": sum(type(value) is not int for value in usage),
            "methods": methods, "per_repository": per_repo,
            "primary": {"contrast": "graphify_jev_lexical - graphify_lexical hit_at_1",
                        "delta": delta, "bootstrap": primary_interval,
                        "repositories_improved": repo_improvements,
                        "frozen_gate_supported": primary_supported if not any(
                            row["status"] != "ok" for row in provider_rows) else False},
            "edge_filter": {"jev": accepted_metrics, "lexical_equal_count": lexical_metrics,
                            "precision_delta": edge_delta, "bootstrap": edge_interval,
                            "frozen_gate_supported": edge_supported if not any(
                                row["status"] != "ok" for row in provider_rows) else False},
            "limits": "Execution observation is not assertion effectiveness. Same three repositories as prior study, "
                      "new source-selected functions. No complete coding-agent outcomes or dollar cost.",
            "total_runner_wall_seconds": time.perf_counter() - run_started,
        }
        write(stage / "rankings.json", rankings)
        write(stage / "candidate-pairs.json", candidate_pairs)
        write(stage / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", action="append", required=True, help="name=/absolute/path")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    roots = {}
    for value in args.repo:
        name, sep, path = value.partition("=")
        if not sep or name in roots:
            parser.error("Use unique name=/absolute/path repository arguments")
        roots[name] = Path(path).resolve(strict=True)
    summary = run(roots, args.out, args.env_file)
    print(json.dumps({key: summary[key] for key in
                      ("targets", "provider_errors", "primary", "edge_filter")}, indent=2))


if __name__ == "__main__":
    main()
