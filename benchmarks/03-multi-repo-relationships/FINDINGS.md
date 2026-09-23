# Round 01 findings

**Decision: the frozen sample supports Jev as a repository-mapping utility.**

The narrow capability tested here is adding exact function/test relationships
that the structural graph missed. It is not a claim that Jev can replace code
search, execute tests, judge assertion quality, or decide which tests are safe to
skip.

## Frozen result

The protocol and 72-request sample were frozen and reviewed in
[PR #5](https://github.com/kgarg2468/jev-map/pull/5) before any live scores or
isolated execution labels were collected. All candidate pairs were absent from
the structural map by construction.

The three pinned repositories passed their full suites before evaluation:
Boltons 519 tests, h11 78 tests, and Pluggy 181 tests. Jev 1.13.0 then completed
all 72 requests with no provider error. Only after the last response did the
runner profile 115 selected tests in isolation.

Three Boltons `BaseTestMixin` methods were not independently collectable by
pytest. Their six candidate pairs were excluded, leaving 210 eligible pairs and
97.2% oracle coverage. The raw lexical candidate set contained 98
execution-observed relationships, or 46.7% of eligible pairs.

At the frozen 0.8 threshold, Jev accepted 39 relationships. Execution observed
34 of them and did not observe five:

| Repository | Eligible pairs | Observed candidates | Jev accepted | Accepted and observed | Observed fraction | Observed coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Boltons | 66 | 10 | 2 | 1 | 50.0% | 10.0% |
| h11 | 72 | 41 | 14 | 13 | 92.9% | 31.7% |
| Pluggy | 72 | 47 | 23 | 20 | 87.0% | 42.6% |
| **Pooled** | **210** | **98** | **39** | **34** | **87.2%** | **34.7%** |

The pooled accepted-observed fraction has a descriptive 95% Wilson interval of
73.3% to 94.4%. The frozen rule required zero provider failures, at least 90%
oracle coverage, one confirmed addition in every repository, at least 80%
pooled observed fraction, and a Wilson lower bound of at least 65%. Every gate
passed.

The 34 confirmed additions cover 23 production functions: one in Boltons, eight
in h11, and fourteen in Pluggy. The same frozen candidates contained observed
relationships for 49 functions, so the result demonstrates useful additions but
also substantial incompleteness.

## What the result establishes

For this source-selected sample, Jev turned a noisy lexical candidate set from
46.7% observed relationships into a conservative set with 87.2% observed
relationships. Those 34 exact edges were absent from the existing structural
graph and would therefore make its repository map more informative.

The 72 sequential provider calls used 232,502 reported input tokens and 15.1
seconds of summed provider wall time. Median request latency was 0.186 seconds;
the slowest was 0.511 seconds. This supports using Jev as a fast filter inside a
larger mapping pipeline. A dollar-cost advantage over an LLM reviewer was not
tested because this run has no matched LLM baseline or fixed provider pricing.

The result does not support exclusive test selection. Jev rejected 64
execution-observed pairs at the frozen threshold. Boltons was particularly weak,
with one confirmed edge among ten observed candidates. Agents must keep normal
search, structural analysis, test execution, and reasoning fallbacks.

The five accepted but unobserved cases were plausible nearby functionality, such
as `_ComplementSet.issubset` beside a broad complement-set test and
`Connection.__init__` beside a chunked-reader test. This is the main precision
failure mode to target: semantic neighborhood is not exact execution.

## Exploratory threshold view

This table was computed after the frozen decision and did not affect it:

| Threshold | Accepted | Accepted and observed | Observed fraction | Observed coverage |
| ---: | ---: | ---: | ---: | ---: |
| 0.5 | 84 | 68 | 81.0% | 69.4% |
| 0.6 | 70 | 56 | 80.0% | 57.1% |
| 0.7 | 59 | 48 | 81.4% | 49.0% |
| 0.8 | 39 | 34 | 87.2% | 34.7% |
| 0.9 | 21 | 19 | 90.5% | 19.4% |

Scores below 0.8 may be useful as ranked hints even though they should not become
high-confidence map edges. A new threshold policy needs another frozen corpus;
this result must not be used both to tune and validate one.

## Scope and archive

The run used Python 3.14.7 on Linux x86-64. Exact upstream commits are recorded
in [`repositories.json`](repositories.json), and the source/request identities
are in [`freeze.json`](freeze.json). The immutable
[`round-01`](rounds/round-01) archive contains exact requests, responses, usage,
test reports, call traces, joined pairs, preflight output, and the primary
summary. Its completion manifest validates all 306 data files, and the private
credential does not occur in the archive.

Runtime call observation is narrower than test usefulness and does not show that
a test asserts the target's behavior. The source may also have appeared in the
provider's training data. This study does not measure whether coding agents solve
tasks faster or more reliably with the map; that remains the next separate
experiment.
