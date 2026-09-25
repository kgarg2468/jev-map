# Popular-repository replication

## Question and scope

Does benchmark 05's result hold on widely used Python projects? Benchmark 05
found that adding Jev's accepted test links to a Graphify-plus-lexical ranking
raised first-test hits from 97/134 to 105/134, and that Jev's accepted links were
observed in execution more often than an equal number of cheap lexical picks.
Both results came from Boltons, h11, and Pluggy. This study repeats the same
frozen methods on five new repositories.

The repositories were chosen for recognition, not sampled from a population:
Flask, FastAPI, yt-dlp, LangChain (the `langchain-core` package in `libs/core`),
and Graphify itself. Popular source code is likely in the Jev provider's
training data. A positive result supports the same narrow claim on these
projects; it is not evidence about repositories in general, complete coding
tasks, or code review.

## Repositories and test subsets

`repositories.json` pins each commit, the checkout root (LangChain uses
`libs/core`), source roots, test paths, and pytest arguments. Only tests that run
offline are included. Every deselection and its reason is recorded in the
configuration before the freeze; tests outside the declared subset are simply
absent from the oracle, never counted as negative evidence. While preparing
environments, each subset was run once under the profiler to measure runtime
and thread behaviour; those traces are not read by the selection code, are not
archived, and were deleted before the freeze. One sampling-frame decision
followed that preparation: yt-dlp's site extractors (`yt_dlp/extractor`) are
excluded because only the excluded online download tests run them. A narrower,
coverage-derived frame proposed during preparation was rejected, since it would
choose targets by coverage. Each repository
runs under its own virtual environment. Interpreter paths are operational
inputs and are not part of the frozen configuration; exact interpreter versions
are archived with the results.

## Frozen sample and run order

1. Build the source-only `jev-map` index for each pinned root. Keep every
   production function under the declared source roots, minus declared
   excludes. Sort by SHA-256 of the fixed seed, repository name, and exact
   function ID, and choose the first 48 per repository. Do not filter on
   structural, lexical, or Graphify links, or on test coverage.
2. Record commits, file hashes, index diagnostics, selected function IDs, all
   parsed test IDs, structural test links, the up-to-three lexical candidates per
   target, and exact Jev request hashes in `rounds/round-00-freeze/freeze.json`
   with a checksum manifest. Commit and publish the freeze before provider calls
   or test-call profiling. Targets with no lexical candidate get no Jev request.
3. Verify the frozen identities, run each declared test subset as preflight,
   build Graphify `graphifyy==0.9.67` with `extract --code-only --no-cluster`,
   and collect Jev `jev-1.13.0` responses. Archive requests, responses, usage,
   graphs, timing, and errors.
4. Only after both methods finish, collect each declared test subset and run
   every collected test file in its own pytest process under `popular_profile`,
   files in collection order. Recording is identical to benchmark 05's profiler,
   and so is the thread rule: a case that overlaps a pre-existing worker or
   leaves a surviving worker is unknown and its test ineligible. Workers a test
   started get up to one second to finish at its end, with their calls still
   recorded, before survival is judged. Parameterized cases combine under the
   source test function. Disclose every denominator. Runtime call observation
   means execution, not an effective assertion.

   This differs from benchmark 05, which profiled each suite in one session.
   Environment preparation showed long-lived background threads (LangSmith's
   cached client in langchain-core, FastAPI's TestClient workers) that made most
   later tests in a session ineligible. Per-file processes confine a surviving
   worker to its own file; the grace period stops a worker that is merely
   shutting down from disqualifying its test. The rule is applied identically to
   all five repositories and fixed before the freeze. A file that fails when run
   alone makes the oracle incomplete, which fails both gates.

## Compared methods and outcomes

Methods, ordering, threshold (0.8), lexical fallback, metrics, and bootstrap
procedure are exactly those of benchmark 05's protocol, using this study's
seeds. The primary outcome is pooled hit@1 of Graphify + Jev + lexical minus
Graphify + lexical, over targets with at least one observed eligible test.

## Decision

Claim that the benchmark 05 **toolbelt improvement replicates on these
repositories** only if pooled hit@1 improves by at least 5 percentage points,
the stratified bootstrap lower bound is above zero, and at least three of the
five repositories improve. Claim that Jev is a **better edge filter than cheap
ranking** here only with at least a 5-point precision gain over an equal-number
lexical selection and a positive function-cluster bootstrap lower bound.
Anything short of a gate is reported as inconclusive or negative, with the
numbers. Integration-style suites (Flask, FastAPI) make execution of core
functions common, which can raise every method's scores; per-repository
results are reported alongside the pooled ones.

Archive every round under `rounds/<round>/` with a checksum manifest. Never
change a completed round, and never tune a threshold on these oracle labels and
call the result held out.
