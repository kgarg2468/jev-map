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

The [live round](rounds/round-01-live) completed after the freeze was published.
Read the [findings and decision](FINDINGS.md) before generalizing the result.
Ordinary search and test execution remain required agent tools.

To run another independent round, use a **new** output directory. Jev credentials
must be supplied through tokenstash, and the runner never records them:

```sh
tokenstash need TYPESAFE_API_KEY
uv tool install graphifyy==0.9.67
uv run --extra benchmark python -m benchmarks.toolbelt_study \
  --repo boltons=/path/to/boltons \
  --repo h11=/path/to/h11 \
  --repo pluggy=/path/to/pluggy \
  --env-file /path/to/private/.env.local \
  --out benchmarks/05-heldout-toolbelt/rounds/<new-round>
```
