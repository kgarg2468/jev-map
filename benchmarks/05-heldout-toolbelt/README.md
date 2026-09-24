# Held-out Graphify + Jev toolbelt test

Read the [prospective protocol](PROTOCOL.md) before interpreting results.
Functions are sampled independently of Graphify, Jev, and runtime labels; the
earlier Jev-selected candidate comparison remains [exploratory](../04-product-baselines/README.md).

Generate the frozen target and request manifest from clean checkouts at the
commits in [`repositories.json`](repositories.json):

```sh
uv run --extra benchmark python -m benchmarks.heldout_freeze \
  --repo boltons=/path/to/boltons \
  --repo h11=/path/to/h11 \
  --repo pluggy=/path/to/pluggy
```

Live results will be published in a later, immutable round after this freeze
is committed. Ordinary search and test execution remain required agent tools.
