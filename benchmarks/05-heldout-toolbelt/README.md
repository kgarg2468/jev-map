# Held-out Graphify + Jev toolbelt test

Read the [prospective protocol](PROTOCOL.md) before interpreting results.
Functions are sampled independently of Graphify, Jev, and runtime labels; the
earlier Jev-selected candidate comparison remains [exploratory](../04-product-baselines/README.md).

The committed [freeze round](rounds/round-00-freeze) contains the source-only
target and request manifest. Regenerate it for verification in a **new** output
directory from clean checkouts at the commits in
[`repositories.json`](repositories.json):

```sh
uv run --extra benchmark python -m benchmarks.heldout_freeze \
  --repo boltons=/path/to/boltons \
  --repo h11=/path/to/h11 \
  --repo pluggy=/path/to/pluggy \
  --out /tmp/jev-map-freeze-verify
cmp benchmarks/05-heldout-toolbelt/rounds/round-00-freeze/freeze.json \
  /tmp/jev-map-freeze-verify/freeze.json
```

Live results will be published in a later, immutable round after this freeze
is committed. Ordinary search and test execution remain required agent tools.
