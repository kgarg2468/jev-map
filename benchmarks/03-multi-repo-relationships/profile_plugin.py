"""Pytest plugin that records Python calls during one selected test protocol."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(os.environ["JEV_MAP_PROFILE_ROOT"]).resolve(strict=True)
OUTPUT = Path(os.environ["JEV_MAP_PROFILE_OUTPUT"])
OBSERVED: set[str] = set()
REPORTS: list[dict] = []


def profile(frame, event, arg):
    if event != "call":
        return
    try:
        path = Path(frame.f_code.co_filename).resolve()
        relative = path.relative_to(ROOT).as_posix()
    except (OSError, ValueError):
        return
    OBSERVED.add(f"{relative}::{frame.f_code.co_qualname}")


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    previous = sys.getprofile()
    previous_thread = threading.getprofile()
    sys.setprofile(profile)
    threading.setprofile(profile)
    try:
        yield
    finally:
        sys.setprofile(previous)
        threading.setprofile(previous_thread)


def pytest_runtest_logreport(report):
    REPORTS.append({
        "nodeid": report.nodeid,
        "when": report.when,
        "outcome": report.outcome,
        "wasxfail": getattr(report, "wasxfail", None),
    })


def pytest_sessionfinish(session, exitstatus):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        "observed": sorted(OBSERVED),
        "pytest_exit": int(exitstatus),
        "reports": REPORTS,
    }, indent=2) + "\n")
