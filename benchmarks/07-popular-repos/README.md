# Popular-repository replication

Benchmark 05's frozen Graphify + Jev test-finding comparison, repeated on
Flask, FastAPI, yt-dlp, LangChain (`libs/core`), and Graphify. See the
[protocol](PROTOCOL.md) for scope, gates, and what a result can and cannot show.

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
