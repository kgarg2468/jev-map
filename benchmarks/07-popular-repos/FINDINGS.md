# Round 01 findings

**Decision: neither frozen gate is met.** Benchmark 05's first-test improvement
did not replicate on Flask, FastAPI, yt-dlp, langchain-core, and Graphify. The
edge-filter comparison shows a large precision gap in Jev's favour, but its
frozen gate requires every provider request to succeed, and 7 of 240 failed.

The [protocol](PROTOCOL.md) and [freeze](rounds/round-00-freeze) were published
in [PR #13](https://github.com/kgarg2468/jev-map/pull/13) before any provider
call or test-call label. All five suites passed preflight, and the per-file
execution oracle completed with no failing file.

## First test to inspect (primary)

Among the 191 sampled functions with at least one observed, eligible test:

| Repository | Positive targets | Graphify + lexical hit@1 | Add Jev hit@1 |
| --- | ---: | ---: | ---: |
| Flask | 46 | 25 | 26 |
| FastAPI | 43 | 22 | 22 |
| yt-dlp | 22 | 9 | 9 |
| langchain-core | 34 | 11 | 13 |
| Graphify | 46 | 30 | 30 |
| **Pooled** | **191** | **97 (50.8%)** | **100 (52.4%)** |

The paired gain is 1.57 percentage points with a stratified bootstrap 95%
interval of 0 to +3.57 points, and two of five repositories improved. The gate
needed at least 5 points, a positive lower bound, and three repositories. Jev
rarely changed the first suggestion because it accepted few links: 48 of 637
eligible candidate pairs. Both Graphify toolbelts found an observed test in
their first three suggestions for 132 of 191 targets. Lexical ranking alone
got 73 first-test hits.

## Accepted Jev links versus cheap ranking

Of the 637 eligible frozen candidate pairs, 155 were observed in execution. At
the 0.8 threshold Jev accepted 48, and 39 were observed (81.3%). A lexical ranker
given the same 48-link budget found 13 (27.1%). The difference is 54.2 points,
with a function-cluster bootstrap interval of +37.0 to +70.0 points.

| Repository | Jev accepted, observed | Equal-budget lexical, observed |
| --- | ---: | ---: |
| Flask | 13 / 14 | 1 / 1 |
| FastAPI | 9 / 10 | 2 / 15 |
| yt-dlp | 4 / 4 | 2 / 4 |
| langchain-core | 6 / 11 | 2 / 7 |
| Graphify | 7 / 9 | 6 / 21 |

The frozen edge gate is still **not supported**: the protocol treats any provider
error as a failed round for both gates, and seven Graphify requests failed.
Six returned HTTP 400 at 146-160 KB and one exceeded jev-map's 200 KB request
limit; all were large source-and-test excerpts, not transient errors. As a
post-hoc check, excluding those seven targets leaves Jev at 39/48 and the
equal-budget lexical selection at 16/48. That check was chosen after seeing the
result and is not a held-out claim.

Jev remained conservative. Its accepted links covered 39 of the 155 observed
candidate pairs (25%), so a missing link still says nothing about whether a
test is relevant. Compared with benchmark 05 (102/117 accepted links observed,
lexical 77/117), Jev's precision held while cheap lexical ranking fell sharply
on these larger repositories.

## Coverage, cost, and limits

| Repository | Eligible source tests | Graphify nodes | Graphify build |
| --- | ---: | ---: | ---: |
| Flask | 370 / 373 | 2,091 | 6.3 s |
| FastAPI | 2,185 / 2,291 | 8,728 | 14.4 s |
| yt-dlp | 553 / 771 | 11,222 | 17.7 s |
| langchain-core | 1,824 / 1,880 | 10,117 | 8.9 s |
| Graphify | 4,942 / 5,068 | 14,355 | 14.4 s |

Ineligible tests were uncollected by the declared subset, failed or skipped
their call phase, or overlapped a surviving worker thread (yt-dlp's networking
tests account for most of its 171 thread-unknown tests). Forty-nine sampled
functions had no observed eligible test and are excluded from hit@1 only.

The 233 successful Jev requests reported 1,490,325 input tokens and 55.9
seconds of summed provider time, about $0.063 at TypeSafe's published input
price. The whole runner took 23 minutes. Execution observation is not assertion
quality, the repositories were chosen for recognition, and their source is
likely in the provider's training data.

## Provenance

The freeze checksum covered selection code but not the runner or profiler.
[Round 02](rounds/round-02-provenance/provenance.json) records every runner and
oracle file at the freeze commit and at the run commit. Only
`popular_profile.py` changed between them, to keep profiling workers started
during the thread grace period, before any provider call or label existed.
Nothing has changed since the run, and all 3,508 files in the live round match
its completion manifest.

## What follows

This round supports two narrower statements than benchmark 05 did: Jev's
accepted test links were again mostly confirmed by execution, and on these
repositories they were far more precise than cheap lexical ranking at the same
budget. It does not support adding Jev to a Graphify toolbelt to improve the
first suggested test. Oversized requests need an explicit size policy, which
would need a new frozen corpus to evaluate.
