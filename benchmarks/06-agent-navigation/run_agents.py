"""Run the frozen coding-agent task in paired, isolated Graphify toolbelts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from benchmarks.archive import staged_round
from jev_map.index import build

HERE = Path(__file__).resolve().parent
FREEZE = HERE / "rounds/round-01-freeze/freeze.json"
CONFIG = HERE / "config.json"
INPUTS = HERE / "rounds/round-02-tool-inputs"
CHEAP = HERE / "rounds/round-03-cheap-hints"
ARMS = ("graphify", "jev", "cheap")


def arm_order(seed: str, task_id: str) -> list[str]:
    return sorted(ARMS, key=lambda arm: hashlib.sha256(f"{seed}\0{task_id}\0{arm}".encode()).hexdigest())


def prompt_for(task: dict, graph: Path, hint: dict) -> str:
    return f"""You are a coding agent investigating a function in this repository.

Target implementation: {task['function']}

Find up to three runnable pytest test node IDs, ranked by how likely they are to actually execute this exact implementation. The highest-ranked ID matters most. You may inspect source, use rg, query Graphify's native code-only graph at {graph}, and run tests with the repository's .venv-bench/bin/python. Use at least one native Graphify `query` or `explain` command, for example:
uvx --from graphifyy==0.9.67 graphify query "Which tests exercise {task['function']}?" --graph {graph}

You may use ordinary file and test commands to check evidence. Do not edit files, browse the web, or inspect benchmark oracle files or other experiment arms. A graph path or optional hint is a lead, not proof of execution. Do not assume a missing link means a test is irrelevant.

Optional extra relationship hint (JSON): {json.dumps(hint, sort_keys=True)}

Return ONLY one JSON object, with keys `tests` (array of zero to three exact runnable pytest node IDs), `evidence` (brief explanation), and `commands_run` (array of commands you actually ran). Do not include markdown. Parameter variants may be given without the bracket suffix if every listed variant exercises the target. If uncertain, return the best grounded options rather than invented IDs.
"""


def parse_answer(text: str) -> dict:
    value = json.loads(text.strip())
    if (not isinstance(value, dict) or set(value) != {"tests", "evidence", "commands_run"}
            or not isinstance(value["tests"], list) or len(value["tests"]) > 3
            or any(not isinstance(item, str) for item in value["tests"])
            or len(value["tests"]) != len(set(value["tests"]))
            or not isinstance(value["evidence"], str)
            or not isinstance(value["commands_run"], list)
            or any(not isinstance(item, str) for item in value["commands_run"])):
        raise ValueError("Invalid agent answer schema")
    return value


def tool_compliance(events: list[dict]) -> tuple[bool, bool, int]:
    commands = [event["item"] for event in events
                if event.get("type") == "item.completed"
                and event.get("item", {}).get("type") == "command_execution"]
    graphify_used = any(item.get("exit_code") == 0 and
                        ("graphify query" in item.get("command", "")
                         or "graphify explain" in item.get("command", ""))
                        for item in commands)
    web_used = any(event.get("item", {}).get("type") in {"web_search", "browser"}
                   for event in events)
    return graphify_used, web_used, len(commands)


def effective_input_hash(model: str, effort: str, prompt: str, graph: Path, timeout: int) -> str:
    value = {"model": model, "effort": effort, "prompt": prompt,
             "graph_sha256": hashlib.sha256(graph.read_bytes()).hexdigest(),
             "timeout_seconds": timeout}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def environment() -> dict[str, str]:
    value = os.environ.copy()
    value.pop("PYTHONPATH", None)
    value["PYTHONDONTWRITEBYTECODE"] = "1"
    for key in list(value):
        if key.endswith("_API_KEY") or key.endswith("_TOKEN"):
            value.pop(key)
    return value


def run_one(codex: Path, root: Path, task: dict, arm: str, graph: Path,
            spool: Path, timeout: int) -> dict:
    ident = task["id"]
    slot = spool / ident / arm
    meta = slot / "meta.json"
    if arm == "jev":
        hint = json.loads((INPUTS / f"{ident}-jev-hint.json").read_text())
    elif arm == "cheap":
        hint = json.loads((CHEAP / f"{ident}-cheap-hint.json").read_text())
    else:
        hint = {"target": task["function"], "links": []}
    prompt = prompt_for(task, graph, hint)
    config = json.loads(CONFIG.read_text())
    input_sha256 = effective_input_hash(config["agent_model"], config["agent_effort"], prompt, graph, timeout)
    if meta.exists():
        cached = json.loads(meta.read_text())
        if cached.get("input_sha256") != input_sha256 or (slot / "prompt.txt").read_text() != prompt:
            raise ValueError(f"Stale cached agent run for {ident} {arm}; use a new spool")
        return cached
    slot.mkdir(parents=True, exist_ok=True)
    (slot / "prompt.txt").write_text(prompt)
    answer_path = slot / "answer.txt"
    argv = [str(codex), "exec", "-m", config["agent_model"], "--sandbox", "danger-full-access",
            "--strict-config", "--disable", "browser_use", "--disable", "in_app_browser",
            "--skip-git-repo-check", "--ephemeral", "--json", "-C", str(root),
            "-c", 'web_search="disabled"',
            "-c", f'model_reasoning_effort="{config["agent_effort"]}"',
            "-o", str(answer_path), prompt]
    started = time.monotonic()
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, cwd=root,
                                   env=environment(), stdin=subprocess.DEVNULL, timeout=timeout)
        status = "ok" if completed.returncode == 0 else "cli_error"
        stdout, stderr = completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    seconds = time.monotonic() - started
    (slot / "events.jsonl").write_text(stdout)
    (slot / "stderr.txt").write_text(stderr)
    events = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    graphify_used, web_used, command_count = tool_compliance(events)
    answer = None
    if status == "ok" and web_used:
        status = "invalid_web"
    elif status == "ok" and not graphify_used:
        status = "no_graphify"
    if status == "ok" and answer_path.exists():
        try:
            answer = parse_answer(answer_path.read_text())
        except (ValueError, json.JSONDecodeError):
            status = "invalid_answer"
    elif status == "ok":
        status = "missing_answer"
    usage = [event.get("usage") for event in events if event.get("type") == "turn.completed"]
    row = {"task": ident, "arm": arm, "status": status, "wall_seconds": seconds,
           "usage": usage[-1] if usage else None, "answer": answer,
           "input_sha256": input_sha256,
           "graphify_used": graphify_used, "web_used": web_used,
           "command_count": command_count}
    meta.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    return row


def run(codex: Path, roots: dict[str, Path], out: Path, spool: Path,
        graph_workdir: Path, timeout: int, max_workers: int = 3) -> dict:
    freeze = json.loads(FREEZE.read_text())
    config = json.loads(CONFIG.read_text())
    if set(roots) != {entry["name"] for entry in freeze["repositories"]}:
        raise ValueError("Repository arguments must match the freeze")
    jobs = []
    for entry in freeze["repositories"]:
        root = roots[entry["name"]].resolve(strict=True)
        if subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip() != entry["commit"]:
            raise ValueError(f"{entry['name']} commit differs from freeze")
        if build(root)["snapshot"] != entry["snapshot_sha256"]:
            raise ValueError(f"{entry['name']} source differs from freeze")
        graph = (INPUTS / f"{entry['name']}-graph.json").resolve(strict=True)
        for task in entry["tasks"]:
            working = {}
            for arm in ARMS:
                path = graph_workdir / task["id"] / arm / "graph.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    if path.read_bytes() != graph.read_bytes():
                        raise ValueError(f"{task['id']} working graph differs from archived input")
                else:
                    shutil.copyfile(graph, path)
                working[arm] = path.resolve(strict=True)
            jobs.append((root, task, working, graph))
    def run_task(job):
        root, task, graphs, _ = job
        return [run_one(codex, root, task, arm, graphs[arm], spool, timeout)
                for arm in arm_order(config["seed"], task["id"])]
    grouped = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(run_task, job): job[1]["id"] for job in jobs}
        for future in as_completed(futures):
            ident = futures[future]
            grouped[ident] = future.result()
            print(f"{len(grouped)}/{len(jobs)} {ident}: "
                  + ", ".join(f"{row['arm']}={row['status']}" for row in grouped[ident]), flush=True)
    rows = [row for _, task, _, _ in jobs for row in grouped[task["id"]]]
    for _, task, graphs, source_path in jobs:
        source = source_path.read_bytes()
        for path in graphs.values():
            if path.read_bytes() != source:
                raise ValueError(f"{task['id']} working graph was modified")
    for entry in freeze["repositories"]:
        root = roots[entry["name"]].resolve(strict=True)
        if build(root)["snapshot"] != entry["snapshot_sha256"]:
            raise ValueError(f"{entry['name']} source changed during agent runs")
    summary = {"agent_model": config["agent_model"], "effort": config["agent_effort"],
               "timeout_seconds": timeout, "jobs": rows}
    with staged_round(out) as stage:
        shutil.copytree(spool, stage / "runs")
        (stage / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", type=Path, default=Path("/home/kg/.local/opt/node/bin/codex"))
    parser.add_argument("--repo", action="append", required=True)
    parser.add_argument("--out", type=Path, default=HERE / "rounds/round-06-agent-runs")
    parser.add_argument("--spool", type=Path, default=Path("/tmp/jev-agent-runs-spool-v3"))
    parser.add_argument("--graph-workdir", type=Path, default=Path("/tmp/jev-agent-working-graphs-v3"))
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-workers", type=int, default=3)
    args = parser.parse_args()
    roots = {}
    for item in args.repo:
        name, sep, path = item.partition("=")
        if not sep or name in roots:
            parser.error("Expected unique name=/absolute/path")
        roots[name] = Path(path)
    run(args.codex, roots, args.out, args.spool, args.graph_workdir,
        args.timeout, args.max_workers)


if __name__ == "__main__":
    main()
