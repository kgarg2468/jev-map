# Agent test-navigation findings

## Decision

**Do not add the current Jev hint to every coding-agent test-navigation task.**
On 24 frozen functions in three repositories, the native Graphify code graph
plus an LLM agent, source search, and pytest found an executing test first on
23 tasks. Giving the same agent a bounded Jev hint also found 23. A cheap LLM
hint found 24. Jev passed neither preregistered agent-quality gate. Its
inference call was much cheaper and faster than the cheap LLM hint, but it did
not improve the completed agent outcome or reduce commands on this sample.

This is a negative result for this **on-demand test hint policy** and task
distribution. It does not reverse the earlier positive map-ranking result, and
it does not decide whether Jev could help a different coding or review task.

| Arm | Correct first test | Hit@3 | Sum of per-task latency, including hint | Public API list-price equivalent |
| --- | ---: | ---: | ---: | ---: |
| Graphify + agent | 23/24 | 23/24 | 896.6 s | $1.371 |
| Graphify + Jev + agent | 23/24 | 23/24 | 889.9 s | $1.415 |
| Graphify + cheap LLM + agent | 24/24 | 24/24 | 1,073.4 s | $1.497 |

The Jev minus Graphify hit@1 difference was **0/24**. The function-paired,
repository-stratified bootstrap interval over this sample is [0, 0]; that
degenerate interval does **not** rule out effects on unseen tasks. Jev was
one task behind the cheap LLM, with a descriptive difference of −4.17
percentage points and interval [−12.5, 0]. Jev and Graphify both missed
`attrs-n-03` (`_ClassBuilder.add_replace`); Jev returned no accepted hint for
it. The cheap LLM hint pointed to a `TestEvolve` test that the oracle observed
calling the target. This one task accounts for the whole quality difference.

The Jev arm's mean paired end-to-end latency was 0.28 seconds lower per task
than Graphify alone, with a descriptive 95% interval of −4.09 to +3.45
seconds. That is not evidence of a speed gain. The cheap LLM arm was 7.37
seconds slower per task, interval +2.86 to +12.02 seconds. These are sums and
per-task comparisons of individual request durations; the three task workers
ran concurrently, so the table is not total wall-clock time for the study.

## What the cost result does and does not show

The 24 Jev decisions used 62,630 reported input tokens. At TypeSafe's
[published price of $0.042 per million input tokens, with output free](https://typesafe.ai/blog/introducing-system-one-models-and-jev),
their list-price equivalent is $0.00263. The archived Jev CLI calls took 8.31
seconds in total, plus 0.61 seconds to build the local maps once. The first
request was made in preflight and then reused from the exact-request cache;
the cost includes all 24 unique receipts.

The 24 low-effort GPT-5.6 Luna hints used 350,625 input tokens, including
249,856 cached input tokens, and 2,174 output tokens. At the
[published Luna API rates](https://developers.openai.com/api/docs/models/gpt-5.6-luna),
that is $0.02776, with 133.68 seconds of recorded call time. Jev hint
generation was about 10.6 times cheaper and 16.1 times faster in this harness.
Both used the same candidate source excerpts, but Codex's LLM harness added
prompt/context overhead; these are measured workflow costs, not an intrinsic
equal-token model benchmark.

The agent costs in the first table use reported Codex token usage and the
current [GPT-6 Sol standard API rates](https://developers.openai.com/api/docs/pricing).
They are **API list-price equivalents, not an invoice**; Codex account billing
may differ. Adding Jev cost about $0.044 more than Graphify alone in total on
this sample because the agent arm used slightly more billable tokens despite
Jev's inexpensive hint. This difference is small and one run per task cannot
separate a consistent cost effect from agent variance. Graphify's common
graph-build cost is excluded from all arms; Jev's one-time map refresh is
included in its latency.

## What was actually tested

The [preregistered protocol](PROTOCOL.md) froze eight functions each from
cachetools, Tenacity, and attrs before treatment outputs. Six functions per
repository had no structural test path and two had one. Every selected
function had at least one independently observed eligible test. The
[freeze audit](AUDIT.md) verified that every runnable test collected at the
pinned commits appeared in the profiles and that corrected test-ID and
test-root handling left all 24 tasks and strata unchanged. The oracle records
execution, not assertion quality.

All three arms used the same `gpt-6-sol` medium agent, the pinned source, the
native `graphifyy==0.9.67` **code-only** graph, ordinary `rg`, and pytest.
Every one of the 72 valid agent runs executed a native Graphify query or
explanation, used `rg`, and invoked pytest. None used web search, the hidden
oracle, or another arm's Jev map. Jev and Luna hints were generated from the
same three lexical test candidates per function; only accepted links at the
frozen 0.8 threshold were shown to the agent. The
[independent result audit](rounds/round-08-agent-audit/audit.json) reconstructed
all three hit counts from raw agent answers and call traces.

The first agent wave could not run local commands in a read-only Codex
sandbox. The next diagnostic wave exposed Graphify's query-cache write beside
the graph input. Both are [archived as invalid](rounds/) and excluded. The
scored wave used working graph copies per arm and kept the archived graphs
unchanged. [Round 02](rounds/round-02-tool-inputs/) contains exact Jev
receipts and Graphify graphs; [round 03](rounds/round-03-cheap-hints/) contains
cheap LLM prompts, responses, and usage; [round 06](rounds/round-06-agent-runs/)
contains all agent prompts and event logs; [round 07](rounds/round-07-score/)
contains raw call oracles and scores. Every round has a SHA-256 completion
manifest.

A [posthoc provenance audit](rounds/round-09-provenance-audit/audit.json) rebuilt
each native Graphify graph from the pinned, clean checkout and found all three
byte-identical to the archived inputs. It reconstructed the exact Jev request
from each frozen target and source snapshot, matched all 24 canonical receipts
and their accepted links, reconstructed all 72 agent prompts, and found 72
distinct agent threads. A guarded rescore produced a byte-identical `score.json`.
This audit preserved every earlier round; the runner now rejects stale cached
slots, mismatched supplied Graphify graphs, and unrelated cost receipts.

## Limits and next gate

The Graphify baseline already solved 95.8% of these test-selection tasks, so
there was little room for an additive hint. The experiment used one agent run
per task; it does not measure model-run variance. It tests navigation from a
known function in Python repositories, not finding an unknown bug, writing a
fix, reviewing a PR, or Graphify's optional semantic extraction and broader
product. No missing link is evidence that a test is safe to skip.

The earlier [held-out ranker study](../05-heldout-toolbelt/FINDINGS.md) found
that Jev moved the correct first test from 97/134 to 105/134 in a deterministic
Graphify-plus-lexical ranking policy. This new agent study shows that a
reasoning agent with search and test execution can erase that intermediate
ranking gain. Keep `enrich-symbol` opt-in for research or agents with a real
retrieval bottleneck. A new adoption claim needs a **new, frozen** corpus of
harder repository tasks and complete bug-fix/review outcomes, with per-task
compute budgets and repeats. These 24 oracle labels must not be reused as a
fresh holdout for a tuned prompt or threshold.
