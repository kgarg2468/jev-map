"""Publish complete benchmark rounds atomically on the destination filesystem."""

import hashlib
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path


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
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("Output appeared while running; refusing to replace it")
        staging.rename(destination)
