"""Record calls for each test, including workers that begin and end within it.

Cases overlapping a pre-existing or surviving worker are marked unknown. A
worker profiler may outlive its creator, so its calls are never reused as a
label for another test case.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(os.environ["JEV_MAP_PROFILE_ROOT"]).resolve(strict=True)
OUTPUT = Path(os.environ["JEV_MAP_PROFILE_OUTPUT"])
CASES: dict[str, dict] = {}
REPORTS: dict[str, list[dict]] = {}


@lru_cache(maxsize=4096)
def source_path(filename: str) -> str | None:
    if filename.startswith("<"):
        return None
    try:
        path = Path(filename).resolve()
        if path.suffix != ".py" or not path.is_file():
            return None
        return path.relative_to(ROOT).as_posix()
    except (OSError, ValueError):
        return None


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    observed: set[str] = set()
    runner = threading.current_thread()
    preexisting_worker = any(thread is not runner for thread in threading.enumerate())
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

    # The default profile covers workers created during this test. Pre-existing
    # workers cannot be instrumented here; survivors may call code afterward.
    # Both conditions make this case ineligible for an execution oracle.
    previous = sys.getprofile()
    previous_thread = threading.getprofile()
    sys.setprofile(profile)
    threading.setprofile(profile)
    try:
        yield
    finally:
        sys.setprofile(previous)
        threading.setprofile(previous_thread)
        surviving_worker = any(thread is not runner for thread in threading.enumerate())
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
