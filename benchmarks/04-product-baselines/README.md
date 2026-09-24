# Graphify and cheap-ranker comparison

Round 01 is a **retrospective, exploratory** comparison using the exact pinned
Boltons, h11, and Pluggy repositories and execution labels from benchmark 03.
The 210 eligible pairs were selected for that earlier Jev study: they are the
top three lexical candidates for each selected function and have **no path in
jev-map's structural graph by construction**. This sample is unsuitable for a
general claim that Jev beats Graphify or another product.

The runner builds [Graphify](https://github.com/Graphify-Labs/graphify)
`graphifyy==0.9.67` in local code-only mode with clustering disabled. It maps
the exact function and test symbols by Graphify's generated ID, checks their
source path and label, and follows directed `calls` edges. A second, more
permissive reading also follows `indirect_call`. Import and generic reference
edges do not establish execution. A cheap IDF-overlap ranker uses the same
candidate text already available to jev-map. It emits exactly 39 links, matching
Jev's frozen 0.8-threshold output count. The test oracle is the earlier isolated
execution profile; it was **not** collected anew for this comparison.

| Method on this selected sample | Emitted | Execution-observed | Not observed |
| --- | ---: | ---: | ---: |
| Graphify `calls` | 1 | 1 | 0 |
| Graphify `calls` + `indirect_call` | 4 | 4 | 0 |
| Cheap lexical ranker, top 39 | 39 | 32 | 7 |
| Jev, score at least 0.8 | 39 | 34 | 5 |

Jev yielded more observed additions than Graphify's directed code-only call
graph on these selected candidates. Graphify generated a broader graph locally
with zero model tokens. Jev's gain over the cheap ranker at equal output count
was only two observed links. This round does not establish lower cost, faster
agent work, complete-test recall, or superiority over Graphify as a whole.

First provision the pinned Graphify package in the `uv` cache using your normal
package-installation setup: `uv tool install graphifyy==0.9.67`. The benchmark
then runs `uvx` offline with a small environment allowlist, so Graphify cannot
inherit provider credentials and its run does not depend on proxy or package
index settings. Reproduce in a fresh output directory with checkouts at the exact commits in
[`repositories.json`](../03-multi-repo-relationships/repositories.json):

```sh
uv run --extra benchmark python -m benchmarks.graphify_compare \
  --repo boltons=/path/to/boltons \
  --repo h11=/path/to/h11 \
  --repo pluggy=/path/to/pluggy \
  --out benchmarks/04-product-baselines/rounds/<new-round>
```

The [offline validated round archive](rounds/round-03-offline) contains the full
Graphify outputs, sanitized command logs and timings, pair-by-pair decisions
with graph paths, summary, and SHA-256 completion manifest. It rejects
untracked input and removes credentials from Graphify's process environment.
The [initial exploratory round](rounds/round-01-retrospective) and
[first validated round](rounds/round-02-validated) remain archived unchanged;
all three rounds produced the same graph hashes and accuracy counts.
Raw Graphify graph files retain `extracted_sources` checkout paths as generated
by the tool; scoring uses relative `source_file` paths. The new prospective benchmark must
sample functions independently of these products, include structural links,
and evaluate against all runnable tests before an adoption claim.
