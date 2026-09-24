"""Posthoc provenance check for the already-published agent navigation result.

This writes a new round; it never edits the frozen inputs or scored runs.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

from benchmarks.archive import staged_round
from jev_map.enrich import make_request, proposals
from jev_map.index import build, digest
from jev_map.provider import validate_response

HERE = Path(__file__).resolve().parent
ROUNDS = HERE / "rounds"
ARMS = ("graphify", "jev", "cheap")


def module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


runner = module("provenance_agent_runner", "run_agents.py")
tools = module("provenance_tool_inputs", "run_tool_inputs.py")
score = module("provenance_score", "score.py")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def run(roots: dict[str, Path], out: Path, graph_workdir: Path) -> dict:
    for round_path in sorted(ROUNDS.iterdir()):
        if round_path.is_dir():
            score.verify_round(round_path)
    freeze = json.loads((ROUNDS / "round-01-freeze/freeze.json").read_text())
    config = json.loads((HERE / "config.json").read_text())
    inputs = ROUNDS / "round-02-tool-inputs"
    runs = ROUNDS / "round-06-agent-runs"
    agent_summary = json.loads((runs / "summary.json").read_text())
    jobs = {(job["task"], job["arm"]): job for job in agent_summary["jobs"]}
    expected_count = sum(len(entry["tasks"]) for entry in freeze["repositories"])
    if (set(roots) != {entry["name"] for entry in freeze["repositories"]}
            or len(jobs) != expected_count * len(ARMS)
            or len(agent_summary["jobs"]) != len(jobs)
            or agent_summary["agent_model"] != config["agent_model"]
            or agent_summary["effort"] != config["agent_effort"]):
        raise ValueError("Frozen repositories or agent job configuration differ")

    report = {"repositories": [], "requests": [], "agent_inputs": [],
              "fresh_graphs_equal_archived": True, "score_equal_archived": False}
    thread_ids = set()
    with staged_round(out) as stage:
        for entry in freeze["repositories"]:
            name = entry["name"]
            root = roots[name].resolve(strict=True)
            commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            if commit != entry["commit"] or subprocess.check_output(
                    ["git", "-C", str(root), "status", "--porcelain"], text=True).strip():
                raise ValueError(f"{name} checkout differs from frozen clean commit")
            data = build(root)
            if data["snapshot"] != entry["snapshot_sha256"]:
                raise ValueError(f"{name} source snapshot differs from freeze")
            graph = inputs / f"{name}-graph.json"
            rebuilt, graph_log = tools.verified_graph(root, graph, config["graphify_package"])
            graph_sha = sha(rebuilt)
            (stage / f"{name}-graph-build.json").write_text(json.dumps(graph_log, indent=2) + "\n")
            targets = {task["function"] for task in entry["tasks"]}
            tokens, receipt_wall = score.checked_jev_receipts(inputs / name / "receipts", targets)
            report["repositories"].append({"name": name, "commit": commit,
                                           "snapshot_sha256": data["snapshot"],
                                           "graph_sha256": graph_sha,
                                           "canonical_receipts": len(targets),
                                           "jev_input_tokens": tokens,
                                           "receipt_wall_seconds": receipt_wall})
            for task in entry["tasks"]:
                ident, target = task["id"], task["function"]
                candidate = proposals(data, config["candidate_limit"], symbol=target)
                if len(candidate) != 1:
                    raise ValueError(f"{ident} has no reproducible Jev candidate batch")
                function, peers = candidate[0]
                request = make_request(data, function, peers, config["model"])
                request_hash = digest(request)
                receipt = json.loads((inputs / name / "receipts" / f"{request_hash}.json").read_text())
                if receipt["request"] != request or receipt["request_sha256"] != request_hash:
                    raise ValueError(f"{ident} receipt does not match pinned source and candidates")
                scores = validate_response(request, receipt["response"])
                expected_links = [{"test": peer["id"], "evidence": "inferred",
                                   "score": scores[f"b{i}"],
                                   "receipt": f"receipts/{request_hash}.json"}
                                  for i, peer in enumerate(peers)
                                  if scores[f"b{i}"] >= config["jev_threshold"]]
                jev_hint = json.loads((inputs / f"{ident}-jev-hint.json").read_text())
                if jev_hint["target"] != target or jev_hint["links"] != expected_links:
                    raise ValueError(f"{ident} Jev hint differs from verified receipt")
                report["requests"].append({"task": ident, "request_sha256": request_hash,
                                           "accepted_links": len(expected_links)})
                for arm in ARMS:
                    working_graph = graph_workdir / ident / arm / "graph.json"
                    if working_graph.read_bytes() != rebuilt:
                        raise ValueError(f"{ident} {arm} working graph differs from fresh extraction")
                    if arm == "jev":
                        hint = jev_hint
                    elif arm == "cheap":
                        hint = json.loads((ROUNDS / f"round-03-cheap-hints/{ident}-cheap-hint.json").read_text())
                    else:
                        hint = {"target": target, "links": []}
                    prompt = runner.prompt_for(task, working_graph.resolve(strict=True), hint)
                    slot = runs / "runs" / ident / arm
                    if (slot / "prompt.txt").read_text() != prompt:
                        raise ValueError(f"{ident} {arm} archived prompt differs from frozen inputs")
                    meta = json.loads((slot / "meta.json").read_text())
                    if meta != jobs[(ident, arm)]:
                        raise ValueError(f"{ident} {arm} slot metadata differs from run summary")
                    events = [json.loads(line) for line in (slot / "events.jsonl").read_text().splitlines()
                              if line.startswith("{")]
                    threads = [event["thread_id"] for event in events if event.get("type") == "thread.started"]
                    if len(threads) != 1 or threads[0] in thread_ids:
                        raise ValueError(f"{ident} {arm} missing or reused agent thread")
                    thread_ids.add(threads[0])
                    report["agent_inputs"].append({
                        "task": ident, "arm": arm, "thread_id": threads[0],
                        "prompt_sha256": sha(prompt.encode()), "graph_sha256": graph_sha,
                        "effective_input_sha256": runner.effective_input_hash(
                            config["agent_model"], config["agent_effort"], prompt,
                            working_graph, agent_summary["timeout_seconds"])})
        with tempfile.TemporaryDirectory(prefix="jev-agent-rescore-") as temporary:
            rescored = Path(temporary) / "score"
            score.run({entry["name"]: ROUNDS / f"round-07-score/{entry['name']}-oracle.json"
                       for entry in freeze["repositories"]}, rescored)
            fresh_score = (rescored / "score.json").read_bytes()
        archived_score = (ROUNDS / "round-07-score/score.json").read_bytes()
        if fresh_score != archived_score:
            raise ValueError("Current guarded scorer differs from archived score")
        report["score_equal_archived"] = True
        report["score_sha256"] = sha(archived_score)
        report["tasks"] = expected_count
        report["agent_runs"] = len(thread_ids)
        report["canonical_receipts"] = sum(item["canonical_receipts"] for item in report["repositories"])
        report["jev_input_tokens"] = sum(item["jev_input_tokens"] for item in report["repositories"])
        (stage / "audit.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", action="append", required=True)
    parser.add_argument("--graph-workdir", type=Path,
                        default=Path("/tmp/jev-agent-working-graphs-v3"))
    parser.add_argument("--out", type=Path, default=ROUNDS / "round-09-provenance-audit")
    args = parser.parse_args()
    result = run(tools.pairs(args.repo), args.out, args.graph_workdir)
    print(json.dumps({key: result[key] for key in ("tasks", "agent_runs", "canonical_receipts",
                                                   "jev_input_tokens", "score_equal_archived")}, indent=2))


if __name__ == "__main__":
    main()
