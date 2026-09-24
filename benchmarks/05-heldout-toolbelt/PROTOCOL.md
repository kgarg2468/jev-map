# Prospective test-finding comparison

## Question and scope

For a coding agent asked which tests exercise a production function, does Jev
make a Graphify-style repository map more useful than a deterministic graph
with a cheap lexical fallback? This tests a **toolbelt addition**, not replacement
of code search, test execution, an LLM reviewer, or the whole Graphify product.

Round 01 reuses three pinned repositories from benchmark 03 but selects **new
production functions** without looking at runtime call labels, Graphify paths,
Jev scores, or candidate availability. The earlier study's 72 target functions
are excluded. Earlier test traces still exist and may include calls to new
functions; the selection code does not read them. Source code may be present in
the Jev provider's training data. A later cross-repository replication is needed
for a broad generalization.

## Frozen sample and run order

1. Build the same source-only `jev-map` index for each pinned commit. Keep every
   production function under the declared source roots, excluding the declared
   test trees and all target functions in benchmark 03's freeze. Sort by SHA-256
   of the fixed seed, repository name, and exact function ID. Choose the first
   48 per repository. Do not filter on structural, lexical, or Graphify links.
2. Record repository commits and file hashes; selected function IDs; all parsed
   test IDs; structural test links; the up-to-three lexical candidates per target;
   and exact Jev request hashes in `freeze.json`. Commit and publish the freeze
   before provider calls or any new test-call profiling.
3. Verify the frozen identities, run each full test suite as preflight, build
   Graphify `graphifyy==0.9.67` with `extract --code-only --no-cluster`, and
   collect Jev `jev-1.13.0` responses for the frozen candidates. Archive exact
   provider requests, responses, usage, Graphify graphs, timing, and errors.
4. Only after both methods finish, execute each full test suite under a pytest
   call profiler that records exact source-path and qualified-function calls per
   test. Parameterized cases combine under the source test function. A test
   with a failing, skipped, timed-out, or uncollectable call phase is ineligible;
   disclose the denominator and missing cases. Runtime call observation means
   execution, not an effective assertion. Never infer that an unobserved link
   makes a test safe to skip.

## Compared methods

All methods may return ordinary lexical suggestions when the graph has fewer
than three test paths. This matches what a coding agent can do with a grep-like
fallback. The method output is ordered and limited to three tests per function.

- **Graphify + lexical:** Directed Graphify `calls` and `indirect_call` paths,
  ordered by fewer inferred edges, then shorter path, then test ID. Fill empty
  slots with the same IDF-overlap lexical ranking available to every method.
- **Graphify + Jev + lexical:** Start with the same Graphify paths. Insert
  Jev-accepted candidate links (score at least 0.8), ordered by score, before
  the lexical fallback. Do not count Jev scores as calibrated probabilities.
- **jev-map structural + lexical:** The product's structural test paths, ordered
  by path length and test ID, then the same lexical fallback.
- **jev-map structural + Jev + lexical:** Same structural paths, then accepted
  Jev links, then lexical fallback.
- **Lexical only:** The common IDF-overlap ranking without a graph.

Graphify's generic `imports`, `references`, and `uses` edges do not assert a
test's execution of a function, so they are not used to create exact test links.
Graphify's native graph exploration remains a separate agent-task evaluation.

## Outcomes and decision

The primary outcome is **hit@1**: among sampled functions for which at least one
eligible test executed the function, how often is the first suggested test
observed? The primary contrast is Graphify + Jev + lexical minus Graphify +
lexical. Report per-repository and pooled paired differences with a stratified,
function-cluster bootstrap 95% interval. Report hit@3, reciprocal rank,
precision among emitted exact edges, observed-test coverage, false suggestions
for functions with no observed test, map build time, provider wall time, and
reported tokens separately. Missing or failed cases count as missing, never as
negative execution evidence.

For the interval, draw the same number of target functions with replacement
within each repository 10,000 times using the fixed bootstrap seed in
`repositories.json`; recompute the pooled paired difference each time and take
the 2.5th and 97.5th percentiles. A target with no observed eligible test is
excluded only from hit@1 and still contributes to false-suggestion reporting.
For the equal-number lexical edge comparison, choose the globally highest IDF
scores from the same frozen candidate pairs until the number equals Jev's
accepted count. Recompute that equal-number selection within each bootstrap
resample. Do not call it a calibrated likelihood comparison.

Claim a useful **Jev toolbelt improvement on this sample** only if primary
hit@1 improves by at least 5 percentage points, the bootstrap lower bound is
above zero, and at least two repositories improve. A positive point estimate
without these gates is inconclusive. A zero or negative point estimate is a
negative result for this policy. To claim Jev is a **better edge filter than
cheap ranking**, additionally compare accepted Jev edges with an equal-number
lexical selection from the same candidate set; require at least a 5-point
precision gain with a positive function-cluster bootstrap lower bound. No
calibration, dollar-cost, or general code-review claim follows from either gate.

Archive every round under `rounds/<round>/` with a checksum manifest. Never
change a completed round or tune a threshold on its oracle labels and treat
the tuned result as held out. A new policy requires another frozen corpus.
