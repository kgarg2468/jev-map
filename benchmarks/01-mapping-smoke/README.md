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

New rounds are built in a temporary sibling and published only after every
artifact is written. `completion.json` records checksums. Interrupted runs never
appear at the final path. A complete archive can still describe a failed provider
request or failed metric: consult its recorded outcomes. Rounds 1 and 2 predate
this archive marker and are retained unchanged.
