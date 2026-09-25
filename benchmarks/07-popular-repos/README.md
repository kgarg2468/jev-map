# Popular-repository replication

Benchmark 05's frozen Graphify + Jev test-finding comparison, repeated on
Flask, FastAPI, yt-dlp, LangChain (`libs/core`), and Graphify. See the
[protocol](PROTOCOL.md) for scope, gates, and what a result can and cannot show.

**Result:** neither frozen gate is met. Adding Jev moved the first-test hits from
97 to 100 of 191. Tests confirmed 39 of Jev's 48 accepted links (81%), against
13 of 48 (27%) for an equal-budget lexical ranker, but 7 of 240 provider requests
failed on size, which fails the edge gate as frozen. See the
[findings](FINDINGS.md), the [live round](rounds/round-01-live), and the
[provenance record](rounds/round-03-provenance/provenance.json).

## Reproduce

Clone each repository at the commit in [`repositories.json`](repositories.json)
(LangChain's root is its `libs/core` directory), create one virtual environment
per repository outside the checkout with the package installed editable plus its
test dependencies, and confirm each declared pytest command passes offline. Then:

```sh
export PYTHONPATH=src:.
python benchmarks/07-popular-repos/freeze.py \
  --repo flask=/abs/flask --repo fastapi=/abs/fastapi --repo yt-dlp=/abs/yt-dlp \
  --repo langchain=/abs/langchain/libs/core --repo graphify=/abs/graphify \
  --out /tmp/check-freeze      # must reproduce rounds/round-00-freeze/freeze.json

python benchmarks/07-popular-repos/run.py \
  --repo flask=/abs/flask --python flask=/abs/venvs/flask/bin/python \
  ... one --repo and --python per repository ... \
  --env-file /private/.env.local --out benchmarks/07-popular-repos/rounds/<new-round>
```

The run refuses to start if any source file, the protocol, the configuration,
or the selection code differs from the freeze. `run.py` changes only operations
relative to `benchmarks/toolbelt_study.py`: a per-repository interpreter,
declared pytest arguments and timeouts, and a three-of-five repository gate.
Methods, threshold, oracle rules, and metrics are imported unchanged.
