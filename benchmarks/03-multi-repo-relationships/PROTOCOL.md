# Execution-blinded multi-repository protocol

This study asks a narrow question: among deterministic lexical test candidates
that have no structural call path to a function, can Jev identify additional
function/test relationships that are observed during isolated test execution?

The study uses pinned snapshots of Boltons, h11, and Pluggy. These repositories
were not part of the five-repository decision study that motivated `jev-map`.
“Execution-blinded” means this harness withholds its runtime observations until
all Jev responses have landed. It does not claim the source was absent from the
provider's training data.

## Frozen selection

1. Build the normal structural map without executing repository code.
2. Restrict target functions to each repository's declared production package
   roots, excluding in-package test trees.
3. Generate up to three lexical test candidates per function, excluding pairs
   already linked structurally. Keep candidates under the declared test root.
4. Keep functions with exactly three candidates.
5. Sort functions by SHA-256 of the fixed seed, repository name, and stable
   `path.py::qualified_name` identifier. Select the first 24 per repository.
6. Record the exact commit, corpus hash, file hashes, selected identifiers, and
   exact Jev request hash in `freeze.json` before live evaluation.

This yields 72 source-selected functions and 216 candidate pairs. Selection uses
source text and repository structure but never runtime labels or Jev scores.

## Evaluation order

The runner verifies every frozen identity and runs each repository's full test
suite as an environment preflight. It then sends all 72 frozen requests to
`jev-1.13.0`, with no retry. Only after the final response does it execute the
selected tests one at a time under a Python call profiler.

The profiler wraps pytest's setup, call, and teardown protocol for the selected
test. A pair is “observed” when that run calls the exact source path and qualified
function name. Parameterized variants selected by one base node ID are combined.
Tests that fail, time out, cannot be selected, or have no passing call phase are
excluded and disclosed. This prevents an all-skipped selection from becoming
negative evidence.

Provider credentials are read only by the TypeSafe client. They are removed from
test subprocess environments and never written to artifacts. Exact requests,
responses, usage, timing, test receipts, and checksums are archived.

## Metrics and decision rule

The primary descriptive metrics are:

- accepted and execution-observed pairs;
- accepted pairs not observed by this oracle;
- execution-observed pairs rejected by Jev;
- observed fraction among accepted pairs, with a descriptive 95% Wilson interval;
- observed candidate coverage among the frozen candidate set;
- per-repository counts and provider/test failures.

The capability is supported on this sample if all 72 provider requests succeed,
at least 90% of candidate pairs have an executable test oracle, at least one
accepted relationship is execution-observed in every repository, the pooled
accepted-observed fraction is at least 80%, and its descriptive Wilson lower
bound is at least 65%.
Exclusive test filtering is outside this study and remains unsupported. A missing
or rejected link never proves a test is irrelevant.

Runtime call observation is not proof that a test asserts the function's behavior.
Non-observation can also result from subprocesses, native code, wrappers, skips,
or profiler limits. Pairs are clustered within functions and repositories, so the
pooled interval is descriptive rather than a population-generalization guarantee.
This benchmark does not measure coding-agent completion, review quality, or ROI.
