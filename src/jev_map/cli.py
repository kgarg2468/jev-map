"""JSON command-line interface for people and coding agents."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .index import build
from .enrich import enrich
from .provider import JevClient, MODEL
from .store import explain_link, load, related_tests, save


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="jev-map")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    refresh = commands.add_parser("refresh", help="Rebuild the map without executing repository code")
    refresh.add_argument("--jev", action="store_true", help="Send candidate source excerpts to TypeSafe for inferred links")
    refresh.add_argument("--max-calls", type=int, default=20)
    refresh.add_argument("--candidates", type=int, default=3)
    refresh.add_argument("--threshold", type=float, default=0.8)
    refresh.add_argument("--model", default=MODEL)
    refresh.add_argument("--env-file", type=Path, help="Read TYPESAFE_API_KEY from an explicit private env file")
    target = commands.add_parser("enrich-symbol", help="Ask Jev about one function on a fresh saved map")
    target.add_argument("symbol")
    target.add_argument("--candidates", type=int, default=3)
    target.add_argument("--threshold", type=float, default=0.8)
    target.add_argument("--model", default=MODEL)
    target.add_argument("--env-file", type=Path)
    target.add_argument("--max-calls", type=int, default=1)
    commands.add_parser("symbols", help="List stable path::qualified_name identifiers")
    related = commands.add_parser("related-tests")
    related.add_argument("symbol")
    explain = commands.add_parser("explain-link")
    explain.add_argument("function")
    explain.add_argument("test")
    serve = commands.add_parser("serve", help="Expose three tools over MCP stdio (optional dependency)")
    serve.add_argument("--jev", action="store_true", help="Allow TypeSafe source uploads during refresh")
    serve.add_argument("--max-calls", type=int, default=20, help="Maximum new Jev requests for the whole server session")
    serve.add_argument("--env-file", type=Path)
    serve.add_argument("--model", default=MODEL)
    args = parser.parse_args(argv)
    try:
        root = args.repo.resolve(strict=True)
        if args.command == "serve":
            from .server import create_server
            create_server(root, jev=args.jev, max_calls=args.max_calls,
                          env_file=args.env_file, model=args.model).run(transport="stdio")
            return 0
        elif args.command == "refresh":
            data = build(root)
            if args.jev:
                data = enrich(root, data, lambda payload: JevClient(env_file=args.env_file)(payload),
                              model=args.model, threshold=args.threshold,
                              candidate_limit=args.candidates, max_calls=args.max_calls)
            save(root, data)
            result = {"snapshot": data["snapshot"], "symbols": len(data["symbols"]),
                      "links": len(data["links"]), "diagnostics": data["diagnostics"]}
            if "enrichment" in data:
                result["enrichment"] = data["enrichment"]["stats"]
        else:
            data = load(root)
            if args.command == "enrich-symbol":
                data = enrich(root, data, lambda payload: JevClient(env_file=args.env_file)(payload),
                              model=args.model, threshold=args.threshold,
                              candidate_limit=args.candidates, max_calls=args.max_calls,
                              symbol=args.symbol)
                save(root, data)
                result = related_tests(data, args.symbol)
            elif args.command == "symbols":
                result = [{k: symbol[k] for k in ("id", "kind", "start", "end")}
                          for symbol in data["symbols"].values()]
            elif args.command == "related-tests":
                result = related_tests(data, args.symbol)
            else:
                result = explain_link(data, args.function, args.test)
        print(json.dumps(result, indent=2))
        if args.command in {"refresh", "enrich-symbol"} and result.get("enrichment", {}).get("errors", 0):
            return 1
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
