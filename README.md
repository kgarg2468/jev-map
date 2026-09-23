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

## Optional Jev relationships

```sh
tokenstash need TYPESAFE_API_KEY
jev-map --repo /path/to/repo refresh --jev --env-file /path/to/private/.env.local --max-calls 20
```

Omit `--env-file` if `TYPESAFE_API_KEY` is already in the environment.
`--jev` explicitly sends selected source excerpts and imports to TypeSafe.
The default refresh is completely local. Provider calls use a fixed HTTPS
endpoint, a 30-second timeout, no redirects, and no automatic retry.

Jev examines up to three lexical test candidates per function, excluding pairs
already connected structurally. Links scoring at least `--threshold 0.8` are
labelled `inferred`. Scores are provider judgments, not calibrated probabilities
of correctness. Candidate generation is incomplete. In one frozen three-repository
study, 34 of 39 accepted relationships at the default threshold were observed in
isolated test execution; this is evidence for conservative map enrichment, not a
general accuracy guarantee.

Exact requests and responses are stored under `.jev-map/receipts/`. Cache identity
includes the model, questions, all candidates, and source context. Repeating a
refresh reuses identical successful requests; changed request context is evaluated
again. Parsing currently rebuilds the whole structural map. `--max-calls 0`
replays cached inferences without needing a key. Model defaults to `jev-1.13.0`;
override with `--model` when deliberately evaluating another model.

Budgets and oversized excerpts leave visible skipped counts. Failed calls retain
structural results, record sanitized errors, and make the CLI exit 1. Query results
include enrichment completeness statistics. Missing usage is reported as unknown,
never zero. Refreshing without `--jev` produces a structural-only map.

## Use from a coding agent

Install the optional [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk):

```sh
python -m pip install '.[mcp]'
jev-map --repo /absolute/path/to/repo serve
```

The server speaks Model Context Protocol (MCP) over standard input/output and
exposes exactly `related_tests(symbol)`, `explain_link(function, test)`, and
`refresh_map()`. Configure an MCP client with command `jev-map` and arguments
`["--repo", "/absolute/path/to/repo", "serve"]`. The process stays bound to that
repository; tools cannot choose another path or request an API key.

Server startup with `serve --jev --max-calls 20 --env-file /private/.env.local`
explicitly allows source uploads. The call limit applies across **all refreshes
in that server session**. Read-only queries never call Jev. Refresh is serialized,
and source changes invalidate queries until refreshed.

## Try the demonstration

```sh
jev-map --repo examples/mini_repo refresh
jev-map --repo examples/mini_repo related-tests normalize
python benchmarks/01-mapping-smoke/run.py --out /tmp/jev-map-round
```

The benchmark runs five original tests and independently records actual function
calls. See [rounds and limitations](benchmarks/01-mapping-smoke/README.md).
This release emits structural and inferred links. Execution-confirmed results are
currently benchmark evidence, not a supported map-import feature.

Two repeated live Jev smoke rounds completed successfully. In this tiny fixture,
Jev added the single execution-observed relationship missing from the structural
map and rejected the other 11 candidates in both runs. This validates the live
integration path only; it is not a general accuracy or agent-performance claim.

The larger execution-blinded study used 72 production functions from pinned
Boltons, h11, and Pluggy snapshots. At the frozen 0.8 threshold, Jev added 34
execution-observed relationships among 39 accepted candidates, with at least one
confirmed addition in every repository. It still missed 64 observed candidates,
so the map remains additive and cannot safely filter tests. See the
[protocol, raw data, and findings](benchmarks/03-multi-repo-relationships/FINDINGS.md).

The mapping study supports adding test relationships, but does not establish
improved complete-agent performance. See the
[next evaluation steps](docs/ROADMAP.md) and the separate
[existing-repository indexing pilot](benchmarks/02-repository-index/README.md).

An [exploratory Graphify and lexical-ranker comparison](benchmarks/04-product-baselines/README.md)
found that Jev yielded more observed nonstructural test links than Graphify's
code-only directed call graph on the earlier selected sample. At equal output
count, Jev found 34 observed links and a cheap lexical ranker found 32; this
does not establish an accuracy or cost advantage over the cheap baseline.

## Development

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

CI runs the test suite and a CLI smoke check on Python 3.11–3.13. Tests require
neither a Jev key nor network access.

MIT licensed. The Jev service is external and requires a separate API key.
