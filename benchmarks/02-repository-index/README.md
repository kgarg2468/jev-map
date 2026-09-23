# Existing repository indexing pilot

This separate test checks that the mapper can parse a real public repository and
return structural relationships. It does **not** check relationship accuracy,
Jev quality, full CLI latency, or agent performance. No repository code is executed.

Round 1 uses [Boltons](https://github.com/mahmoud/boltons). The exact commit,
Python-file hashes, parser diagnostics, counts, and local timing are preserved.
Source text is not copied into these results. Use the commit in `summary.json`:

```sh
git clone https://github.com/mahmoud/boltons /tmp/boltons-pilot
git -C /tmp/boltons-pilot checkout <recorded-commit>
python benchmarks/02-repository-index/run.py \
  --repo /tmp/boltons-pilot --source-url https://github.com/mahmoud/boltons \
  --out /tmp/boltons-new-round
```

The checkout must be unmodified. Each invocation uses a new output directory.
