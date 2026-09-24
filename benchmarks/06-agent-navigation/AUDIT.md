# Freeze audit

The frozen tasks in `round-01-freeze` remain unchanged. Greptile identified
three ways the original selection code could diverge from its intended corpus:
an incomplete pytest profile could pass with exit code 0, structural links
could come from outside the configured test tree, and parameter IDs containing
`::` could normalize incorrectly. The [audit](audit_freeze.py) compares the
profiled case IDs against a new full collection at the pinned commit, restricts
structural links to the configured test roots, and normalizes parameter IDs in
every node-ID component. All 337 cachetools, 184 Tenacity, and 1,412 attrs
collected cases appear in the respective profiles, and **all 24 selected
targets and strata are identical** under the corrected rules. This is a
post-freeze sensitivity audit, not a new selection.

The first, invalid `round-00-freeze` remains archived. Its original `freeze.py`
and `PROTOCOL.md` are preserved in
[`round-02-freeze-audit/invalid-round-provenance`](rounds/round-02-freeze-audit/invalid-round-provenance)
and match the hashes recorded in that invalid artifact. No oracle test-link
labels are published in this audit; they will be released with the completed
agent results.
