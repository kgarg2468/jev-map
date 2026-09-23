"""Atomic local storage and conservative whole-snapshot freshness checks."""

import json
import os
import tempfile
from pathlib import Path

from .index import SCHEMA, digest, snapshot


def directory(root: Path) -> Path:
    path = root.resolve(strict=True) / ".jev-map"
    if path.is_symlink():
        raise ValueError("Refusing a symlinked .jev-map directory")
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def write_json(path: Path, value: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save(root: Path, data: dict) -> None:
    write_json(directory(root) / "map.json", data)


def validate_map(data: object) -> None:
    """Validate the fields query commands consume, including referenced symbols."""
    def require(condition):
        if not condition:
            raise ValueError("Malformed map; run jev-map refresh")

    require(isinstance(data, dict))
    require(data.get("schema") == SCHEMA)
    require(isinstance(data.get("snapshot"), str))
    require(isinstance(data.get("files"), dict))
    require(isinstance(data.get("symbols"), dict))
    require(isinstance(data.get("links"), list))
    require(isinstance(data.get("diagnostics"), list))
    if "enrichment" in data:
        require(isinstance(data["enrichment"], dict))
        require(isinstance(data["enrichment"].get("stats"), dict))
    for ident, symbol in data["symbols"].items():
        require(isinstance(symbol, dict))
        require(symbol.get("id") == ident)
        require(all(isinstance(symbol.get(key), str) for key in ("name", "kind", "path", "text", "file_sha256")))
        require(all(type(symbol.get(key)) is int for key in ("start", "end")))
    for link in data["links"]:
        require(isinstance(link, dict))
        require(all(isinstance(link.get(key), str) for key in ("id", "function", "test", "evidence")))
        require(link["function"] in data["symbols"] and link["test"] in data["symbols"])


def load(root: Path) -> dict:
    path = directory(root) / "map.json"
    if path.is_symlink():
        raise ValueError("Refusing a symlinked map file")
    if not path.exists():
        raise ValueError("No map exists. Run jev-map refresh first.")
    data = json.loads(path.read_text())
    validate_map(data)
    hashes, _ = snapshot(root.resolve(strict=True))
    if digest(hashes) != data["snapshot"]:
        raise ValueError("Map is stale: repository Python files changed. Run jev-map refresh.")
    return data


def resolve(data: dict, name: str) -> str:
    if name in data["symbols"]:
        return name
    matches = [ident for ident, symbol in data["symbols"].items()
               if symbol["name"] == name or symbol["name"].split(".")[-1] == name]
    if len(matches) != 1:
        raise ValueError("Symbol not found or ambiguous; use path.py::qualified_name from jev-map symbols")
    return matches[0]


def related_tests(data: dict, name: str) -> dict:
    ident = resolve(data, name)
    links = [link for link in data["links"] if link["function"] == ident]
    return {"symbol": ident, "snapshot": data["snapshot"], "links": links,
            "diagnostics": data["diagnostics"],
            "enrichment": data.get("enrichment", {}).get("stats"),
            "warning": "Links are incomplete. Absence is not evidence that a test can be skipped."}


def explain_link(data: dict, function: str, test: str) -> dict:
    a, b = resolve(data, function), resolve(data, test)
    return {"function": data["symbols"][a], "test": data["symbols"][b],
            "snapshot": data["snapshot"],
            "links": [link for link in data["links"] if link["function"] == a and link["test"] == b]}
