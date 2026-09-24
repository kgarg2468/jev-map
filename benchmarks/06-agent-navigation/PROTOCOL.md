# Agent test-navigation experiment

## Decision question

For a coding agent investigating a known production function, does a bounded
Jev test-relationship hint improve selection of a test that actually executes
that function when added to Graphify's native code graph, ordinary source
search, agent reasoning, and the ability to run tests? Compare that addition
with a cheap LLM hint built from the same candidate excerpts. This is a test
navigation task, not a claim about full bug-fix or code-review quality.

## Frozen corpus and independent oracle

Use pinned September 2026 snapshots of cachetools, Tenacity, and attrs. These
repositories were not in prior Jev-map evaluation. Their complete local suites
must pass or have only documented skips/xfails before selection. A pytest
profile observes exact function calls in each case. Exclude failed cases and
cases with unknown worker-thread coverage. Combine parameter variants under
their runnable pytest node ID without the parameter suffix. Inherited methods
retain the concrete test class in that ID. Execution is only evidence of a call, not evidence
of an effective assertion. A missing observed call cannot justify skipping a
test in production.

The deterministic selection script chooses, per repository, six observed
production functions with no structural test path and two with a structural
path. It uses a fixed SHA-256 sort over repository, stratum, and symbol ID.
There is no filtering by Jev response, Graphify output, lexical score, or
candidate availability. The freeze records IDs, commits, source hashes, code
and protocol hashes, and a SHA-256 of each full oracle file. Commit and publish
the freeze before any Jev or Graphify output for these targets. Publish the
oracle files only with results, after agent runs.

## Arms and execution

Build a single Graphify `graphifyy==0.9.67` code-only graph for each pinned
repository. All three arms get the same fresh source checkout, native Graphify
`query`, `path`, and `explain`, `rg` and ordinary file reads, a local Python
test environment, and the same `gpt-6-sol` medium agent prompt and time limit.
Each agent task starts in a separate ephemeral context; no arm sees another
arm's answer or oracle. Randomize arm order by frozen seed and task ID.

- **Graphify toolbelt:** no extra relationship hint.
- **Graphify + Jev:** additionally provide the result of exactly one
  `enrich-symbol` request for the target, with up to three lexically generated
  test candidates and the frozen 0.8 acceptance threshold. The agent sees
  accepted inferred links with their evidence label and can ignore them.
- **Graphify + cheap LLM:** additionally provide a `gpt-5.6-luna` low-effort
  judgment of the identical A/B source excerpts. The prompt must ask the same
  binary exercise question, return scores for every candidate, and use the
  same 0.8 threshold. Its input, output, latency, and token usage are archived.

Jev and cheap LLM hints are prepared before agent runs and are hidden from
other arms. No secret reaches an agent checkout. Candidate absence or rejected
scores produce an empty hint with an explicit incompleteness warning. Every
arm may reason, search, run tests, and cite source evidence. The agent returns
up to three exact pytest source-test IDs in ranked order plus its evidence and
commands run. If it cannot identify a test, it returns an empty list.

## Measures and verdict

Primary: paired **hit@1**, whether the first suggested test executed the
target in the independent eligible oracle. Secondary: hit@3, reciprocal rank,
false suggestions, answer validity, test commands run, wall time, agent input
and output tokens, Jev/provider tokens, and estimated dollar cost only when
the model's actual price is independently verified. Report each repository,
structural stratum, and pooled difference. Use a repository-stratified paired
bootstrap over target functions (10,000 resamples) for a descriptive 95%
interval; one agent run per task does not measure run-to-run model variance.

The Jev addition earns a **pilot win on this task distribution** only if its
pooled hit@1 exceeds Graphify alone and the cheap LLM arm by at least 10
percentage points, both paired interval lower bounds exceed zero, and at
least two repositories improve. A loss or inconclusive result must be reported
as such. Even a win here cannot establish broad coding-agent or code-review
ROI. The next gate would be repeated full bug-fix/review tasks on new issues,
with hidden tests and measured compute cost.

Archive each immutable stage under `rounds/<round>/`, including raw prompts,
tool results, provider receipts without credentials, agent event logs, exact
versions, commands, timings, scoring code, and a checksum manifest. Never tune
the threshold or task selection on these results and present the tuned outcome
as held out.

The first local freeze artifact (`round-00-freeze`) was generated before
discovering that cachetools inherits most test methods from a mixin. Its
source-method mapping excluded 260 runnable cachetools cases and it is **invalid
for scoring**. It is retained for audit. `round-01-freeze` is the corrected
published freeze and the only one used below.
