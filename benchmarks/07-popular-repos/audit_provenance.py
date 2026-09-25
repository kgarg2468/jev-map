"""Record which runner and oracle code produced benchmark 07's live round.

The freeze checksum covers selection code only (`freeze.py` and the index,
enrichment, provider, and archive modules). This audit hashes every file the
live run imports or loads, at the freeze commit and at the commit the live
round was run from, lists which changed, and re-verifies the live round's
completion manifest and frozen-sample hash. It writes a new round and never
edits earlier ones.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from benchmarks.archive import staged_round

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
STUDY = HERE.relative_to(PROJECT).as_posix()
# Files the live run reads directly or loads into pytest subprocesses.
DECLARED = [f"{STUDY}/{name}" for name in ("PROTOCOL.md", "repositories.json", "freeze.py", "popular_profile.py",
                                            "popular_collect.py", "blockbuster_profiler_allow.py")]


def loaded_files() -> list[str]:
    """Every project module imported by the runner, found by importing it."""
    code = ("import importlib.util, sys; from pathlib import Path; root = Path(sys.argv[1]); "
            "spec = importlib.util.spec_from_file_location('run07', sys.argv[2]); "
            "module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
            "print('\\n'.join(sorted({Path(m.__file__).resolve().relative_to(root).as_posix() "
            "for m in list(sys.modules.values()) if getattr(m, '__file__', None) "
            "and Path(m.__file__).resolve().is_relative_to(root)})))")
    output = subprocess.check_output([sys.executable, "-c", code, str(PROJECT), str(HERE / "run.py")],
                                     text=True, timeout=120, cwd=PROJECT)
    return [line for line in output.splitlines() if line] + [str(Path(STUDY) / "run.py")]


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(PROJECT), *args], text=True, timeout=60).strip()


def blob_sha256(commit: str, path: str) -> str | None:
    result = subprocess.run(["git", "-C", str(PROJECT), "show", f"{commit}:{path}"],
                            capture_output=True, timeout=60)
    return hashlib.sha256(result.stdout).hexdigest() if result.returncode == 0 else None


def manifest_ok(round_dir: Path) -> dict:
    manifest = json.loads((round_dir / "completion.json").read_text())
    mismatched = [name for name, expected in manifest["files"].items()
                  if hashlib.sha256((round_dir / name).read_bytes()).hexdigest() != expected]
    extra = sorted(path.relative_to(round_dir).as_posix() for path in round_dir.rglob("*")
                   if path.is_file() and path.name != "completion.json"
                   and path.relative_to(round_dir).as_posix() not in manifest["files"])
    return {"status": manifest["status"], "files": len(manifest["files"]),
            "mismatched": mismatched, "unlisted": extra}


def audit(freeze_commit: str, run_commit: str, live: Path) -> dict:
    inventory = sorted(set(loaded_files()) | set(DECLARED))
    files = {path: {"freeze": blob_sha256(freeze_commit, path), "run": blob_sha256(run_commit, path),
                    "current": hashlib.sha256((PROJECT / path).read_bytes()).hexdigest()}
             for path in inventory}
    frozen = HERE / "rounds/round-00-freeze/freeze.json"
    summary = json.loads((live / "summary.json").read_text())
    return {
        "freeze_commit": git("rev-parse", freeze_commit),
        "freeze_commit_time": git("show", "-s", "--format=%cI", freeze_commit),
        "run_commit": git("rev-parse", run_commit),
        "run_commit_time": git("show", "-s", "--format=%cI", run_commit),
        "files": files,
        "changed_between_freeze_and_run": sorted(path for path, row in files.items() if row["freeze"] != row["run"]),
        "changed_since_run": sorted(path for path, row in files.items() if row["run"] != row["current"]),
        "live_round": live.name,
        "live_manifest": manifest_ok(live),
        "live_frozen_sha256_matches": summary["frozen_sha256"] == hashlib.sha256(frozen.read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--run-commit", required=True)
    parser.add_argument("--live", type=Path, default=HERE / "rounds/round-01-live")
    parser.add_argument("--out", type=Path, default=HERE / "rounds/round-02-provenance")
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    result = audit(args.freeze_commit, args.run_commit, args.live.resolve())
    result["note"] = args.note
    with staged_round(args.out) as stage:
        (stage / "provenance.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: result[key] for key in ("changed_between_freeze_and_run", "changed_since_run",
                                                  "live_manifest", "live_frozen_sha256_matches")}, indent=2))


if __name__ == "__main__":
    main()
