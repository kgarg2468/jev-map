# Mapping smoke benchmark

An original five-test demonstration with six function/test execution relationships.
The oracle actually runs each test and records Python call events. It does not use
Jev or the structural extractor to choose the expected relationships.

```sh
python benchmarks/01-mapping-smoke/run.py --out /tmp/jev-map-offline-round
# Optional, explicit provider access:
python benchmarks/01-mapping-smoke/run.py --out /tmp/jev-map-live-round --jev --env-file /path/to/private/.env.local
```

Each round preserves its map, execution oracle, summary, and any actual provider
receipts. Existing outputs are never overwritten. `offline-structural` means
**Jev was not evaluated**. This small demonstration checks the plumbing and exposes
an instance-method gap; it is not proof of accuracy, speed, ROI, or agent improvement.

Larger held-out repository evaluations are a separate next milestone. Do not mix
these smoke rounds with the earlier private research results.

## Live Jev check

Rounds 4 and 5 sent the same frozen candidate requests to `jev-1.13.0` as two
independent live runs. All eight calls succeeded. Each round evaluated 12
candidate relationships, accepted only `Cleaner.compact` → `test_compact` at
0.96, and rejected all 11 unrelated candidates below 0.8. That accepted link was
the one execution-observed relationship missing from the structural map.

The combined structural and Jev map therefore matched all six relationships
observed by this fixture's execution oracle, with no unconfirmed accepted links.
The structural-only map matched five of six. All 12 threshold decisions repeated;
four scores were identical and the largest score change was 0.03. The two rounds
used 10,982 provider-reported input tokens across eight successful requests.

See [`live-comparison.json`](live-comparison.json), then the exact maps, requests,
responses, usage, timing, and checksums under `rounds/round-04-live-jev/` and
`rounds/round-05-live-jev-repeat/`. This is evidence that the live integration
works on one tiny fixture. It does not establish accuracy on unseen repositories,
economic return, or improved coding-agent outcomes.

New rounds are built in a temporary sibling and published only after every
artifact is written. `completion.json` records checksums. Interrupted runs never
appear at the final path. A complete archive can still describe a failed provider
request or failed metric: consult its recorded outcomes. Rounds 1 and 2 predate
this archive marker and are retained unchanged.

Atomic archive publication currently supports Linux (`renameat2` with
`RENAME_NOREPLACE`) and Windows (non-replacing rename). Unsupported platforms or
filesystems fail instead of falling back to a replacing rename. Linux is tested
in CI; this restriction applies to benchmark publication, not the mapping CLI.
