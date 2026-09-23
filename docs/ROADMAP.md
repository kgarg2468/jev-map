# First usable slice

Implemented: Python structural relationships; optional bounded Jev inference;
exact-request receipts; conservative source freshness checks; three MCP tools;
offline execution smoke benchmark. The repository is MIT licensed, with provider
access supplied separately by the operator.

## Evidence still needed

1. Run the live mini-repository round after project key access is available.
   Treat it as a wiring check, not a product accuracy benchmark.
2. Freeze a held-out corpus of real Python repositories and test relationships.
   Compare structural extraction, lexical candidates, actual execution coverage
   where available, and Jev additions. Measure precision and missed relationships
   separately, per repository; candidate-generation misses matter.
3. Measure fresh indexing, repeated refresh after realistic edits, disk usage,
   total query time, and actual provider usage. Current parsing rebuilds the full
   structural map and freshness checks hash all included Python files.
4. Test whether agents find useful tests sooner with an optional map tool.
   Preserve ordinary search and test fallbacks; report complete-task outcomes
   separately from map accuracy. Do not revive default search reranking without
   new supporting evidence.

Potential extensions, each requiring its own evaluation: importing per-test
execution evidence with source identity, framework-aware fixtures and dynamic
dispatch, additional languages/source layouts, documentation/configuration links.

## Boundaries of v0.1

This is a small initial utility. No execution-confirmed link importer, exhaustive
Python analyzer, giant-monorepo performance guarantee, UI, or hosted service is
included. Optional Jev requests send selected source to TypeSafe. Default
operation stays local and never executes repository code. Benchmarks execute
only the explicit original mini-repository fixture.
