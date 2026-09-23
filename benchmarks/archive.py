"""Publish complete benchmark rounds atomically on the destination filesystem."""

import hashlib
import json
import ctypes
import errno
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path


def publish_no_replace(source: Path, destination: Path) -> None:
    """Atomically refuse existing destinations, including empty directories."""
    if os.name == "nt":
        # Windows os.rename always refuses an existing destination.
        source.rename(destination)
        return
    if sys.platform != "linux":
        raise OSError(errno.ENOTSUP, "Benchmark archiving currently supports Linux and Windows")
    # Linux renameat2(RENAME_NOREPLACE), documented at:
    # https://man7.org/linux/man-pages/man2/rename.2.html
    rename = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if rename is None:
        raise OSError(errno.ENOTSUP, "Benchmark archiving requires libc renameat2")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


@contextmanager
def staged_round(destination: Path):
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Choose a new round; existing results are immutable")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{destination.name}.pending-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "round"
        staging.mkdir()
        yield staging
        files = {path.relative_to(staging).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in sorted(staging.rglob("*")) if path.is_file()}
        if not files:
            raise ValueError("Cannot publish an empty benchmark round")
        (staging / "completion.json").write_text(json.dumps({"status": "complete", "files": files}, indent=2) + "\n")
        publish_no_replace(staging, destination)
