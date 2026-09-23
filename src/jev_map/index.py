"""Conservative Python syntax extraction, without importing repository code."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import subprocess
import tokenize
from pathlib import Path

SCHEMA = 1
EXCLUDED = {".git", ".jev-map", ".venv", "venv", "node_modules", "__pycache__", "build", "dist"}
MAX_FILE_BYTES = 500_000


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def source_files(root: Path) -> list[Path]:
    """Use Git's ignore rules when available; never follow directory/file symlinks."""
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Repository must be a directory")
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            check=True, capture_output=True, timeout=30,
        )
        candidates = [root / os.fsdecode(p) for p in result.stdout.split(b"\0") if p]
    except (OSError, subprocess.SubprocessError):
        candidates = []
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not d.startswith(".")
                             and not (Path(directory) / d).is_symlink())
            candidates.extend(Path(directory) / f for f in files)
    included = set()
    for path in candidates:
        relative = path.relative_to(root)
        if path.suffix != ".py" or any(p in EXCLUDED or p.startswith(".") for p in relative.parts):
            continue
        if any((root / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1)):
            continue
        if path.is_file() and path.resolve().is_relative_to(root):
            included.add(path)
    return sorted(included)


def snapshot(root: Path) -> tuple[dict[str, str], dict[str, bytes]]:
    content = {p.relative_to(root).as_posix(): p.read_bytes() for p in source_files(root)}
    hashes = {p: hashlib.sha256(data).hexdigest() for p, data in content.items()}
    return hashes, content


def module_name(path: str) -> str:
    parts = Path(path).with_suffix("").parts
    if parts[0] == "src":
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def imports_in(nodes: list[ast.stmt], module: str, is_package: bool) -> dict[str, str]:
    imports: dict[str, str] = {}
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            imports.pop(node.name, None)
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                package = module.split(".") if is_package else module.split(".")[:-1]
                if node.level > len(package):
                    continue
                base = ".".join(package[:len(package) - node.level + 1] + ([base] if base else []))
            for alias in node.names:
                if alias.name != "*":
                    imports[alias.asname or alias.name] = ".".join(filter(None, (base, alias.name)))
    return imports


def body_nodes(node: ast.AST):
    """Descendants executed in this scope, excluding nested function/class bodies."""
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from body_nodes(child)


def assigned_names(nodes) -> set[str]:
    names = set()
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
    return names


def call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = call_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def build(root: Path) -> dict:
    root = root.resolve(strict=True)
    hashes, contents = snapshot(root)
    symbols, records, diagnostics = {}, {}, []
    canonical: dict[str, list[str]] = {}
    for path, raw in contents.items():
        if len(raw) > MAX_FILE_BYTES:
            diagnostics.append({"path": path, "reason": "file exceeds 500000-byte parsing limit"})
            continue
        try:
            encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
            text = raw.decode(encoding)
            tree = ast.parse(text, filename=path)
        except (SyntaxError, UnicodeError, LookupError) as exc:
            diagnostics.append({"path": path, "reason": type(exc).__name__})
            continue
        module = module_name(path)
        is_package = Path(path).name == "__init__.py"
        imports = imports_in(tree.body, module, is_package)
        # Module assignments can replace imported names/functions; omit uncertain calls.
        module_shadowed = assigned_names(n for stmt in tree.body if not isinstance(
            stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for n in ast.walk(stmt))
        lines = text.splitlines()

        def visit(nodes, prefix=""):
            for node in nodes:
                if isinstance(node, ast.ClassDef):
                    visit(node.body, prefix + node.name + ".")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = prefix + node.name
                    ident = f"{path}::{name}"
                    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                    test_file = any(p in {"test", "tests"} for p in Path(path).parts) or Path(path).stem.startswith("test_") or Path(path).stem.endswith("_test")
                    symbol = {"id": ident, "path": path, "name": name, "module": module,
                              "kind": "test" if test_file and node.name.startswith("test") else "function",
                              "start": start, "end": node.end_lineno, "file_sha256": hashes[path],
                              "text": "\n".join(lines[start - 1:node.end_lineno])}
                    symbols[ident] = symbol
                    canonical.setdefault(".".join(filter(None, (module, name))), []).append(ident)
                    records[ident] = (node, imports, module_shadowed, module, is_package)
                    # Nested functions are intentionally omitted from v0.1.
        visit(tree.body)

    calls = []
    for ident, (node, imports, module_shadowed, module, is_package) in records.items():
        descendants = []
        for stmt in node.body:
            descendants.append(stmt)
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                descendants.extend(body_nodes(stmt))
        local_imports = imports_in(node.body, module, is_package)
        local_shadowed = assigned_names(descendants)
        local_shadowed.update(a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs)
        local_shadowed.update(a.arg for a in (node.args.vararg, node.args.kwarg) if a is not None)
        bindings = {**imports, **local_imports}
        for child in descendants:
            if not isinstance(child, ast.Call):
                continue
            name = call_name(child.func)
            if not name:
                continue
            first, *rest = name.split(".")
            if first in local_shadowed or first in module_shadowed:
                continue
            target = ".".join([bindings[first], *rest]) if first in bindings else ".".join(filter(None, (module, name)))
            matches = canonical.get(target, [])
            if len(matches) != 1:
                continue
            calls.append({"source": ident, "target": matches[0], "line": child.lineno})
    adjacency: dict[str, set[str]] = {}
    for call in calls:
        adjacency.setdefault(call["source"], set()).add(call["target"])
    links = []
    for test, symbol in symbols.items():
        if symbol["kind"] != "test":
            continue
        queue = [(test, [test])]
        seen = {test}
        for current, chain in queue:
            for target in sorted(adjacency.get(current, ())):
                if target in seen:
                    continue
                seen.add(target)
                new_chain = chain + [target]
                queue.append((target, new_chain))
                if symbols[target]["kind"] != "test":
                    links.append({"id": digest([target, test, "structural"]), "function": target,
                                  "test": test, "evidence": "structural", "call_path": new_chain})
    return {"schema": SCHEMA, "snapshot": digest(hashes), "files": hashes,
            "symbols": symbols, "calls": calls, "links": links, "diagnostics": diagnostics}
