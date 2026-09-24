# First usable slice

Implemented: Python structural relationships; optional bounded Jev inference;
exact-request receipts; conservative source freshness checks; four MCP tools;
  offline execution smoke benchmark; two repeated live Jev smoke rounds; and one
frozen three-repository execution study. The repository is MIT licensed, with
provider access supplied separately by the operator.

## Evidence still needed

1. Measure fresh indexing, repeated refresh after realistic edits, disk usage,
   total query time, and actual provider usage. Current parsing rebuilds the full
   structural map and freshness checks hash all included Python files.
2. Test Jev on harder, frozen complete-agent bug-fix and PR-review tasks.
   Preserve ordinary search and test fallbacks; score hidden-task success,
   review precision, time, and compute cost. The first agent test-navigation
   pilot found no benefit at near-ceiling baseline accuracy. Do not default
   Jev hints or revive search reranking without new supporting evidence.

The live mini-repository check is complete: two independent runs made eight
successful calls and repeated every threshold decision. It remains a wiring and
repeatability check, not a product accuracy benchmark.

The multi-repository mapping study is also complete. At the frozen threshold,
34 of 39 accepted candidates were observed in execution, but 64 observed
candidates were rejected. This supports conservative additive edges and rejects
using Jev as an exclusive test filter. See the
[full findings](../benchmarks/03-multi-repo-relationships/FINDINGS.md).

The [held-out Graphify toolbelt comparison](../benchmarks/05-heldout-toolbelt/FINDINGS.md)
found a positive first-test ranking gain and a larger exact-edge precision gain
over equal-count cheap lexical selection on three pinned repositories. The
separate [24-task agent test-navigation study](../benchmarks/06-agent-navigation/FINDINGS.md)
then let the same LLM agent use native Graphify, `rg`, and pytest in every arm.
Graphify alone and Graphify plus Jev both found an executing first test on
23/24 tasks; a cheap LLM hint arm found 24/24. Jev's much lower hint cost did
not create a better completed-agent outcome. Full bug-fix/review task success
and broad product superiority remain unmeasured.

Potential extensions, each requiring its own evaluation: importing per-test
execution evidence with source identity, framework-aware fixtures and dynamic
dispatch, additional languages/source layouts, documentation/configuration links.

## Boundaries of v0.1

This is a small initial utility. No execution-confirmed link importer, exhaustive
Python analyzer, giant-monorepo performance guarantee, UI, or hosted service is
included. Optional Jev requests send selected source to TypeSafe. Default
operation stays local and never executes repository code. Benchmark runners may
execute only their explicitly supplied, pinned repositories.
