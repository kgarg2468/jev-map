"""Read-only structural indexing pilot on an explicitly supplied Git checkout."""

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

from jev_map.index import build
from jev_map.store import related_tests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmarks.archive import staged_round


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with staged_round(args.out) as output:
        summary = run_round(args, output)
    print(json.dumps(summary, indent=2))


def run_round(args, output):
    root = args.repo.resolve(strict=True)
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True)
    if status:
        raise SystemExit("Pilot requires an unmodified checkout")
    started = time.perf_counter()
    data = build(root)
    elapsed = time.perf_counter() - started
    queries = []
    for symbol in sorted({link["function"] for link in data["links"]})[:5]:
        began = time.perf_counter()
        result = related_tests(data, symbol)
        queries.append({"symbol": symbol, "links": len(result["links"]), "seconds": time.perf_counter() - began})
    summary = {"mode": "offline-structural", "source_url": args.source_url, "commit": commit,
               "python": platform.python_version(), "snapshot": data["snapshot"],
               "files": len(data["files"]), "symbols": len(data["symbols"]),
               "test_symbols": sum(s["kind"] == "test" for s in data["symbols"].values()),
               "call_edges": len(data["calls"]), "test_relationships": len(data["links"]),
               "diagnostics": data["diagnostics"], "build_seconds": elapsed,
               "serialized_map_bytes": len(json.dumps(data).encode()), "sample_queries": queries,
               "median_in_memory_query_seconds": statistics.median(q["seconds"] for q in queries) if queries else None,
               "limits": "Single local index run. Queries exclude snapshot validation and disk loading. Relationships are not execution-validated. No Jev calls or agent tasks."}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (output / "source-hashes.json").write_text(json.dumps(data["files"], indent=2) + "\n")
    return summary


if __name__ == "__main__":
    main()
