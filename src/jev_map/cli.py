"""JSON command-line interface for people and coding agents."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .index import build
from .store import explain_link, load, related_tests, save


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="jev-map")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("refresh", help="Rebuild the structural map without executing repository code")
    commands.add_parser("symbols", help="List stable path::qualified_name identifiers")
    related = commands.add_parser("related-tests")
    related.add_argument("symbol")
    explain = commands.add_parser("explain-link")
    explain.add_argument("function")
    explain.add_argument("test")
    args = parser.parse_args(argv)
    try:
        root = args.repo.resolve(strict=True)
        if args.command == "refresh":
            data = build(root)
            save(root, data)
            result = {"snapshot": data["snapshot"], "symbols": len(data["symbols"]),
                      "links": len(data["links"]), "diagnostics": data["diagnostics"]}
        else:
            data = load(root)
            if args.command == "symbols":
                result = [{k: symbol[k] for k in ("id", "kind", "start", "end")}
                          for symbol in data["symbols"].values()]
            elif args.command == "related-tests":
                result = related_tests(data, args.symbol)
            else:
                result = explain_link(data, args.function, args.test)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
