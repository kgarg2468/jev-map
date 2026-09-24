"""Regrade the immutable held-out round with a runner-thread-only oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from benchmarks.archive import staged_round
from benchmarks.heldout_freeze import CONFIG, HERE, freeze
from benchmarks.toolbelt_study import (
    FROZEN, command_result, edge_metrics, edge_precision_interval, equal_lexical,
    method_metrics, oracle_by_source_test, paired_hit_interval, read,
    test_environment, write,
)

ORIGINAL = HERE / "rounds/round-01-live"
METHODS = ("graphify_lexical", "graphify_jev_lexical", "structural_lexical",
           "structural_jev_lexical", "lexical_only")


def audit(roots: dict[str, Path], output: Path) -> dict:
    config = read(CONFIG)
    frozen = read(FROZEN)
    if freeze(config, roots) != frozen:
        raise ValueError("Source, protocol, implementation, or frozen selection has changed")
    completion = read(ORIGINAL / "completion.json")
    if completion["status"] != "complete" or any(
        hashlib.sha256((ORIGINAL / name).read_bytes()).hexdigest() != value
        for name, value in completion["files"].items()
    ):
        raise ValueError("Original round fails its completion manifest")

    original_summary = read(ORIGINAL / "summary.json")
    original_rankings = read(ORIGINAL / "rankings.json")
    original_pairs = read(ORIGINAL / "candidate-pairs.json")
    old_oracle = {repo["name"]: read(ORIGINAL / "oracle" / f'{repo["name"]}-aggregate.json')
                  for repo in config["repositories"]}
    with staged_round(output) as stage:
        new_oracle = {}
        oracle_stats = {}
        profile_runs = {}
        for repo in config["repositories"]:
            name = repo["name"]
            raw_path = stage / "oracle" / f"{name}.json"
            command = [sys.executable, "-m", "pytest", "-q", *repo["test_paths"],
                       "-p", "full_suite_profile"]
            profile_runs[name] = command_result(
                command, roots[name], test_environment(roots[name], repo, raw_path), 900)
            if profile_runs[name]["returncode"] != 0 or not raw_path.is_file():
                raise RuntimeError(f"Runner-thread oracle failed on {name}; no audit published")
            frozen_repo = next(item for item in frozen["repositories"] if item["name"] == name)
            new_oracle[name], oracle_stats[name] = oracle_by_source_test(
                read(raw_path), frozen_repo["test_ids"])
            write(stage / "oracle" / f"{name}-aggregate.json", new_oracle[name])

        rankings = original_rankings
        changed_target_tests = []
        changed_positive_targets = []
        for row in rankings:
            name, function = row["repository"], row["function"]
            old_positive = bool(row["observed_tests"])
            row["observed_tests"] = sorted(
                test for test, oracle_row in new_oracle[name].items()
                if oracle_row["eligible"] and function in oracle_row["observed"])
            if old_positive != bool(row["observed_tests"]):
                changed_positive_targets.append({"repository": name, "function": function})
            for method in row["methods"].values():
                for prediction in method:
                    test = prediction["test"]
                    oracle_row = new_oracle[name][test]
                    prediction["observed"] = (
                        function in oracle_row["observed"] if oracle_row["eligible"] else None)
            for test, oracle_row in new_oracle[name].items():
                old_row = old_oracle[name][test]
                before = (function in old_row["observed"] if old_row["eligible"] else None)
                after = (function in oracle_row["observed"] if oracle_row["eligible"] else None)
                if before != after:
                    changed_target_tests.append({"repository": name, "function": function,
                                                 "test": test, "before": before, "after": after})

        candidate_pairs = original_pairs
        for pair in candidate_pairs:
            oracle_row = new_oracle[pair["repository"]][pair["test"]]
            pair["test_eligible"] = oracle_row["eligible"]
            pair["observed"] = (pair["function"] in oracle_row["observed"]
                                if oracle_row["eligible"] else None)
        methods = {method: method_metrics(rankings, method) for method in METHODS}
        per_repo = {repo["name"]: {method: method_metrics(
            [row for row in rankings if row["repository"] == repo["name"]], method)
            for method in METHODS} for repo in config["repositories"]}
        base = methods["graphify_lexical"]["hit_at_1"]
        treatment = methods["graphify_jev_lexical"]["hit_at_1"]
        delta = treatment - base if base is not None and treatment is not None else None
        primary_interval = paired_hit_interval(rankings, config, "graphify_lexical",
                                               "graphify_jev_lexical")
        repo_improvements = sum(
            per_repo[name]["graphify_jev_lexical"]["hit_at_1"]
            > per_repo[name]["graphify_lexical"]["hit_at_1"]
            for name in per_repo if per_repo[name]["graphify_lexical"]["hit_at_1"] is not None)
        accepted = {(row["repository"], row["function"], row["test"])
                    for row in candidate_pairs if row["test_eligible"] and row["jev_accepted"]}
        lexical = equal_lexical(candidate_pairs, len(accepted))
        accepted_metrics = edge_metrics(candidate_pairs, accepted)
        lexical_metrics = edge_metrics(candidate_pairs, lexical)
        edge_delta = (accepted_metrics["observed_fraction"] - lexical_metrics["observed_fraction"]
                      if accepted else None)
        edge_interval = edge_precision_interval(candidate_pairs, config)
        changed_eligibility = [
            {"repository": name, "test": test, "before": old_oracle[name][test]["eligible"],
             "after": oracle_row["eligible"]}
            for name, tests in new_oracle.items() for test, oracle_row in tests.items()
            if old_oracle[name][test]["eligible"] != oracle_row["eligible"]]
        result = {
            "kind": "runner_thread_oracle_audit",
            "original_completion_sha256": hashlib.sha256(
                (ORIGINAL / "completion.json").read_bytes()).hexdigest(),
            "profiler_sha256": hashlib.sha256(
                (Path(__file__).parent / "full_suite_profile.py").read_bytes()).hexdigest(),
            "runner_thread_only": True,
            "oracle": oracle_stats,
            "profile_runs": profile_runs,
            "changed_eligibility": changed_eligibility,
            "changed_target_test_labels": changed_target_tests,
            "changed_positive_targets": changed_positive_targets,
            "methods": methods,
            "per_repository": per_repo,
            "primary": {"delta": delta, "bootstrap": primary_interval,
                        "repositories_improved": repo_improvements,
                        "frozen_gate_supported": (delta is not None and delta >= 0.05
                                                  and primary_interval["lower_95"] > 0
                                                  and repo_improvements >= 2)},
            "edge_filter": {"jev": accepted_metrics, "lexical_equal_count": lexical_metrics,
                            "precision_delta": edge_delta, "bootstrap": edge_interval,
                            "frozen_gate_supported": (edge_delta is not None and edge_delta >= 0.05
                                                      and edge_interval["lower_95"] > 0)},
            "same_method_metrics": methods == original_summary["methods"],
            "same_primary": (delta == original_summary["primary"]["delta"]
                             and primary_interval == original_summary["primary"]["bootstrap"]),
            "same_edge_filter": (accepted_metrics == original_summary["edge_filter"]["jev"]
                                 and lexical_metrics == original_summary["edge_filter"]["lexical_equal_count"]
                                 and edge_interval == original_summary["edge_filter"]["bootstrap"]),
        }
        write(stage / "audit.json", result)
        write(stage / "regraded-rankings.json", rankings)
        write(stage / "regraded-candidate-pairs.json", candidate_pairs)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", action="append", required=True, help="name=/absolute/path")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    roots = {}
    for value in args.repo:
        name, sep, path = value.partition("=")
        if not sep or name in roots:
            parser.error("Use unique name=/absolute/path repository arguments")
        roots[name] = Path(path).resolve(strict=True)
    result = audit(roots, args.out)
    print(json.dumps({"changed_eligibility": len(result["changed_eligibility"]),
                      "changed_target_test_labels": len(result["changed_target_test_labels"]),
                      "changed_positive_targets": len(result["changed_positive_targets"]),
                      "same_method_metrics": result["same_method_metrics"],
                      "same_primary": result["same_primary"],
                      "same_edge_filter": result["same_edge_filter"],
                      "primary": result["primary"], "edge_filter": result["edge_filter"]},
                     indent=2))


if __name__ == "__main__":
    main()
