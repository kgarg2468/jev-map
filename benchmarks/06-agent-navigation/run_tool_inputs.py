"""Archive Graphify graphs and one bounded Jev hint per frozen target."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from benchmarks.archive import staged_round
from jev_map.index import build

HERE = Path(__file__).resolve().parent
FREEZE = HERE / "rounds/round-01-freeze/freeze.json"
CONFIG = HERE / "config.json"


def command(argv: list[str], *, timeout=90) -> tuple[subprocess.CompletedProcess, float]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    # Credentials reach only the explicit Jev env file, never Graphify or agent logs.
    for key in list(environment):
        if key.endswith("_API_KEY") or key.endswith("_TOKEN"):
            environment.pop(key)
    started = time.monotonic()
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                            env=environment, stdin=subprocess.DEVNULL)
    return result, time.monotonic() - started


def run(cli: Path, env_file: Path, roots: dict[str, Path], graphs: dict[str, Path], out: Path) -> dict:
    freeze = json.loads(FREEZE.read_text())
    config = json.loads(CONFIG.read_text())
    if set(roots) != {entry["name"] for entry in freeze["repositories"]} or set(graphs) != set(roots):
        raise ValueError("Repository and graph arguments must match the freeze")
    summary = {"tasks": [], "graphify_package": config["graphify_package"],
               "jev_model": config["model"], "product_commit": "14731fa"}
    with staged_round(out) as stage:
        for entry in freeze["repositories"]:
            name = entry["name"]
            root = roots[name].resolve(strict=True)
            if subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip() != entry["commit"]:
                raise ValueError(f"{name} commit differs from freeze")
            if build(root)["snapshot"] != entry["snapshot_sha256"]:
                raise ValueError(f"{name} source differs from freeze")
            graph = graphs[name].resolve(strict=True)
            shutil.copyfile(graph, (stage / f"{name}-graph.json"))
            refresh, seconds = command([str(cli), "--repo", str(root), "refresh"])
            if refresh.returncode:
                raise RuntimeError(f"{name} refresh failed: {refresh.stderr[:300]}")
            result = json.loads(refresh.stdout)
            if result["snapshot"] != entry["snapshot_sha256"]:
                raise ValueError(f"{name} refresh snapshot differs from freeze")
            (stage / f"{name}-refresh.json").write_text(refresh.stdout)
            (stage / f"{name}-refresh-time.json").write_text(json.dumps({"wall_seconds": seconds}) + "\n")
            for task in entry["tasks"]:
                target = task["function"]
                result, seconds = command([str(cli), "--repo", str(root), "enrich-symbol", target,
                                           "--env-file", str(env_file), "--model", config["model"],
                                           "--candidates", str(config["candidate_limit"]),
                                           "--threshold", str(config["jev_threshold"]),
                                           "--max-calls", "1"])
                if result.returncode not in (0, 1):
                    raise RuntimeError(f"{task['id']} enrichment failed: {result.stderr[:300]}")
                response = json.loads(result.stdout)
                if response["symbol"] != target or response["snapshot"] != entry["snapshot_sha256"]:
                    raise ValueError(f"{task['id']} returned an unexpected target or snapshot")
                accepted = [{"test": link["test"], "evidence": "inferred", "score": link["score"],
                             "receipt": link["receipt"]}
                            for link in response["links"] if link["evidence"] == "inferred"]
                hint = {"target": target, "links": accepted,
                        "warning": "Inferred links are fallible and incomplete; search and run tests."}
                (stage / f"{task['id']}-jev-hint.json").write_text(json.dumps(hint, indent=2) + "\n")
                summary["tasks"].append({"id": task["id"], "repo": name,
                                         "returncode": result.returncode,
                                         "wall_seconds": seconds,
                                         "accepted": len(accepted),
                                         "usage": response.get("enrichment")})
            source_receipts = root / ".jev-map/receipts"
            dest_receipts = stage / name / "receipts"
            if source_receipts.exists():
                shutil.copytree(source_receipts, dest_receipts)
            if build(root)["snapshot"] != entry["snapshot_sha256"]:
                raise ValueError(f"{name} source changed during hint collection")
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
    parser.add_argument("--jev-map-cli", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--repo", action="append", required=True)
    parser.add_argument("--graph", action="append", required=True)
    parser.add_argument("--out", type=Path, default=HERE / "rounds/round-02-tool-inputs")
    args = parser.parse_args()
    summary = run(args.jev_map_cli, args.env_file, pairs(args.repo), pairs(args.graph), args.out)
    print(json.dumps({"tasks": len(summary["tasks"]),
                      "requests": sum(item["usage"]["requests"] for item in summary["tasks"]),
                      "accepted": sum(item["accepted"] for item in summary["tasks"])}, indent=2))


if __name__ == "__main__":
    main()
