"""Archive a new round; never overwrite a prior result. Live Jev is explicit."""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from jev_map.enrich import enrich, proposals
from jev_map.index import build, digest
from jev_map.provider import JevClient

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
from benchmarks.archive import staged_round


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--jev", action="store_true")
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    with staged_round(args.out) as output:
        summary = run_round(args, output)
    print(json.dumps(summary, indent=2))
    if not summary["structural_contract_passed"]:
        raise SystemExit("Structural fixture regression; see archived results")


def run_round(args, output):
    executed = subprocess.run([sys.executable, str(HERE / "oracle.py")], capture_output=True, text=True, check=True)
    oracle = json.loads(executed.stdout)
    truth = {(edge["function"], edge["test"]) for edge in oracle["relationships"]}
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "repo"
        shutil.copytree(REPO / "examples/mini_repo", root, ignore=shutil.ignore_patterns("__pycache__", ".jev-map"))
        started = time.perf_counter()
        data = build(root)
        structural_seconds = time.perf_counter() - started
        candidates = {(function["id"], peer["id"]) for function, peers in proposals(data) for peer in peers}
        if args.jev:
            data = enrich(root, data, JevClient(env_file=args.env_file), max_calls=10)
        structural = {(link["function"], link["test"]) for link in data["links"] if link["evidence"] == "structural"}
        inferred = {(link["function"], link["test"]) for link in data["links"] if link["evidence"] == "inferred"}
        def metric(pairs):
            return {"relationships": len(pairs), "execution_confirmed": len(pairs & truth),
                    "unconfirmed": len(pairs - truth), "missed_observed": len(truth - pairs)}
        summary = {"mode": "live-jev" if args.jev else "offline-structural",
                   "snapshot": data["snapshot"], "truth_relationships": len(truth),
                   "structural": metric(structural), "lexical_plus_structural": metric(candidates | structural),
                   "jev_plus_structural": metric(inferred | structural) if args.jev else None,
                   "structural_seconds": structural_seconds,
                   "structural_contract_passed": not bool(structural - truth) and len(structural & truth) >= 5,
                   "enrichment": data.get("enrichment", {}).get("stats"),
                   "implementation_sha256": digest({p.name: p.read_text() for p in sorted((REPO / "src/jev_map").glob("*.py"))}),
                   "limits": "Five original demonstration tests, not independent product-quality evidence. Execution is not assertion effectiveness."}
        for name, value in (("summary.json", summary), ("oracle.json", oracle), ("map.json", data)):
            (output / name).write_text(json.dumps(value, indent=2) + "\n")
        receipts = root / ".jev-map/receipts"
        if receipts.exists():
            shutil.copytree(receipts, output / "receipts")
    return summary


if __name__ == "__main__":
    main()
