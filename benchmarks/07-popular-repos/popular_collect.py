"""Write collected pytest node IDs to JEV_MAP_COLLECT_OUTPUT, one per line.

Used with `--collect-only` so the runner does not depend on a project's
configured output verbosity.
"""

from __future__ import annotations

import os
from pathlib import Path


def pytest_collection_finish(session):
    Path(os.environ["JEV_MAP_COLLECT_OUTPUT"]).write_text(
        "".join(item.nodeid + "\n" for item in session.items))
