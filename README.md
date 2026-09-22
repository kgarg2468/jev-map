# jev-map

Evidence-labelled repository maps for coding agents. Start with the question:
**Which tests are connected to this function, and what supports that connection?**

Under active development. Python first. Jev adds fallible hints to a structural
map; the agent still reasons, searches, and runs tests. A missing link never
means a test can safely be skipped.

## Install and use

Requires Python 3.11 or later. The core has no runtime dependencies.

```sh
python -m pip install .
jev-map --repo /path/to/repo refresh
jev-map --repo /path/to/repo symbols
jev-map --repo /path/to/repo related-tests 'src/pkg/core.py::normalize'
jev-map --repo /path/to/repo explain-link 'src/pkg/core.py::normalize' 'tests/test_core.py::test_space'
```

Commands return JSON. `refresh` writes `.jev-map/map.json` without importing or
executing repository code. Add `.jev-map/` to your repository's `.gitignore`:
the local map contains source excerpts. Git ignored files and symlinks are
excluded. Without Git, hidden and common generated directories are excluded.
Queries reject maps after any included Python file is added, changed, or deleted.

Structural links follow unambiguous, syntactically resolved calls, including
import aliases and transitive calls. These are potential call paths, not proof
of execution or useful assertions. Dynamic dispatch, re-exports, nested functions,
fixtures, and custom source roots are not fully resolved. Oversized or invalid
Python files produce visible diagnostics. No link does not mean no relevant test.

Next: optional Jev enrichment with exact request provenance, then an agent
interface and reproducible benchmark.

## Development

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

CI runs the test suite and a CLI smoke check on Python 3.11–3.13. Tests require
neither a Jev key nor network access.

MIT licensed. The Jev service is external and requires a separate API key.
