"""Per-test call profiler for benchmark 07.

Same recording and thread rule as `benchmarks/full_suite_profile.py`, with one
change: at the end of a test, workers the test started get up to
`JEV_MAP_THREAD_GRACE_SECONDS` (default 1.0) to finish, and their calls are
still recorded. A case is unknown if any worker existed before it began or is
still alive after the grace period. The runner starts one pytest process per
test file, so a surviving worker can only affect later tests in its own file.

Paths are resolved with `os.path` functions bound at import, because some suites
patch `os.name` or `pathlib` during a test and would otherwise break recording.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = str(Path(os.environ["JEV_MAP_PROFILE_ROOT"]).resolve(strict=True))
_realpath, _isfile = os.path.realpath, os.path.isfile
OUTPUT = Path(os.environ["JEV_MAP_PROFILE_OUTPUT"])
GRACE = float(os.environ.get("JEV_MAP_THREAD_GRACE_SECONDS", "1.0"))
CASES: dict[str, dict] = {}
REPORTS: dict[str, list[dict]] = {}


@lru_cache(maxsize=4096)
def source_path(filename: str) -> str | None:
    if filename.startswith("<"):
        return None
    try:
        path = _realpath(filename)
        if not path.endswith(".py") or not path.startswith(ROOT + "/") or not _isfile(path):
            return None
        return path[len(ROOT) + 1:]
    except (OSError, ValueError):
        return None


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    observed: set[str] = set()
    runner = threading.current_thread()
    before = set(threading.enumerate())
    preexisting_worker = any(thread is not runner for thread in before)
    threaded = False
    thread_start_code = threading.Thread.start.__code__

    def profile(frame, event, arg):
        nonlocal threaded
        if event != "call":
            return
        if frame.f_code is thread_start_code:
            threaded = True
        relative = source_path(frame.f_code.co_filename)
        if relative is not None:
            observed.add(f"{relative}::{frame.f_code.co_qualname}")

    previous = sys.getprofile()
    previous_thread = threading.getprofile()
    sys.setprofile(profile)
    threading.setprofile(profile)
    try:
        yield
    finally:
        sys.setprofile(previous)
        threading.setprofile(previous_thread)
        deadline = time.monotonic() + GRACE
        for thread in threading.enumerate():
            if thread is not runner and thread not in before:
                thread.join(max(0.0, deadline - time.monotonic()))
        surviving_worker = any(thread is not runner and thread.is_alive()
                               for thread in threading.enumerate())
        CASES[item.nodeid] = {"observed": sorted(observed),
                              "threaded": threaded,
                              "thread_coverage_unknown": preexisting_worker or surviving_worker}


def pytest_runtest_logreport(report):
    REPORTS.setdefault(report.nodeid, []).append({
        "when": report.when, "outcome": report.outcome,
        "wasxfail": getattr(report, "wasxfail", None),
    })


def pytest_sessionfinish(session, exitstatus):
    for nodeid, row in CASES.items():
        row["reports"] = REPORTS.get(nodeid, [])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"pytest_exit": int(exitstatus), "cases": CASES},
                                 indent=2, sort_keys=True) + "\n")
