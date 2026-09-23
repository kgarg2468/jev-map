# Multi-repository relationship study

This benchmark evaluates source-selected, non-structural function/test candidates
on pinned Boltons, h11, and Pluggy snapshots. Read [`PROTOCOL.md`](PROTOCOL.md)
before interpreting any future results.

Create exact checkouts, install the project's benchmark extra, and verify that the
full suites pass. The frozen selection is reproducible with:

```sh
python benchmarks/03-multi-repo-relationships/study.py freeze \
  --repo boltons=/path/to/boltons \
  --repo h11=/path/to/h11 \
  --repo pluggy=/path/to/pluggy
```

After the protocol and `freeze.json` are reviewed and merged, a live run uses:

```sh
python benchmarks/03-multi-repo-relationships/study.py run \
  --repo boltons=/path/to/boltons \
  --repo h11=/path/to/h11 \
  --repo pluggy=/path/to/pluggy \
  --out benchmarks/03-multi-repo-relationships/rounds/<new-round> \
  --env-file /path/to/private/.env.local
```

The run order is fixed in code: repository preflight, every Jev request, then the
execution oracle. The output directory is published atomically only after all
artifacts and a checksum manifest have been written.
