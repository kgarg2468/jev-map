# Round 01 held-out findings

**Decision:** The frozen rule supports Jev as a selective test-finding utility
added to a Graphify-style map on this sample. It supports neither replacing
Graphify nor a claim that a coding agent completes work faster or cheaper.

The [protocol](PROTOCOL.md) and [source-only freeze](rounds/round-00-freeze)
were committed in [PR #8](https://github.com/kgarg2468/jev-map/pull/8)
before the live Jev responses or new per-test call traces were collected.
The 144 target functions are disjoint from benchmark 03's targets. All three
pinned repositories passed preflight and profiled full-suite execution; Jev
completed 144 requests with zero provider errors.

## First test to inspect

Among the 134 target functions with at least one execution-observed, eligible
source test, the frozen toolbelts produced:

| Repository | Positive targets | Graphify + lexical hit@1 | Add Jev hit@1 | Net correct first tests |
| --- | ---: | ---: | ---: | ---: |
| Boltons | 38 | 28/38 (73.7%) | 28/38 (73.7%) | 0 |
| h11 | 48 | 34/48 (70.8%) | 38/48 (79.2%) | +4 |
| Pluggy | 48 | 35/48 (72.9%) | 39/48 (81.2%) | +4 |
| **Pooled** | **134** | **97/134 (72.4%)** | **105/134 (78.4%)** | **+8** |

The paired improvement is 5.97 percentage points. The preregistered,
repository-stratified function bootstrap gives a descriptive 95% interval of
+0.75 to +11.45 points. The positive lower bound, at least five-point gain,
and gains in two repositories satisfy the frozen primary gate.

Jev changed the first suggestion for 21 functions. This was a **ranking** gain:
both Graphify toolbelts found an observed test in the first three suggestions
for 126/134 positive targets (94.0%). The same eight-hit net gain appears when
adding Jev to `jev-map`'s structural map: 99/134 to 107/134 correct first tests.
The ten remaining targets had no observed eligible test and are excluded from
hit@1, but their 30 suggestions remain visible in the raw rankings.

## High-confidence edges versus a cheap filter

Of 432 frozen Jev candidate pairs, 423 had an eligible test oracle; 220 were
execution-observed. At the frozen score threshold of 0.8, Jev accepted 117
eligible links, of which 102 were observed (87.2%). A deterministic lexical
ranker supplied the same 117-link output budget and found 77 observed links
(65.8%). The difference is 21.37 percentage points, with a function-cluster
bootstrap 95% interval of +11.46 to +31.15 points. This passes the separate
frozen edge-filter gate. Jev still rejected 118 observed candidates. It must
never be used to rule out tests.

This held-out result resolves the ambiguity from the earlier retrospective
sample, where Jev found 34 observed links in 39 suggestions and the cheap
ranker found 32. It does so on new functions sampled without selecting for
missing structural links. It remains a comparison on these three repositories,
not a population-wide accuracy guarantee.

## Cost, coverage, and interpretation

Graphify's code-only builds took 4.49 seconds across the three repositories
and reported zero model tokens. Jev's 144 sequential requests took 50.43 seconds
of summed provider wall time and reported 451,630 input tokens. The complete
runner, including test preflight, graph builds, Jev calls, full-suite profiling,
and analysis, took 70.18 seconds. No fixed provider price or matched LLM-review
baseline was measured, so this does not prove lower dollar cost or ROI.

The frozen source index recognized 607 test symbols; 582 were eligible after
profiling. Twenty-five Boltons source test symbols were not collected, and 50
additional collected Boltons cases did not map to a source test symbol, notably
inherited tests and functions inside conditional syntax. h11 and Pluggy had
complete recognition among their frozen test symbols. The primary result is
for tests the mapper could represent; nine ineligible suggestions occurred in
both Graphify toolbelts. Runtime calls include setup and teardown and do not
show that a test makes a useful assertion. The provider may have seen public
source during training.

The [immutable live round](rounds/round-01-live) contains exact Jev requests,
responses, usage, Graphify graphs, full-suite traces, eligibility, per-function
rankings, candidate-pair scores, timing, and checksums. All 301 archived files
passed the completion-manifest check, and the injected credential was not
present in the archive. The next necessary test is whether a coding agent
actually completes repository tasks faster or more reliably with these hints.
