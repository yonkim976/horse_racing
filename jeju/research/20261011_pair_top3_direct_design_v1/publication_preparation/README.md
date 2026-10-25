# Direct pair Top3: publication append preparation

Status: preparation only, 2026-10-11. No conclusion was published and no central file was written. The authoritative model execution plan remains `jeju/research/20261011_pair_top3_direct_v1/PLAN.md` and `INPUT_CONTRACT.md`; this folder only prepares a future, root-reviewed central append.

## Current central inventory

The fresh read-only snapshot in [preappend_pair_top3_direct_20261011b](preappend_pair_top3_direct_20261011b/snapshot_manifest.json) captured 28 immediate files in `jeju/research/conclusions/`, 24 registered topics, and a highest numbered conclusion prefix of `21`. Prefix `22` is the proposal target for this snapshot and remains subject to compare-and-swap at any later apply. The earlier `central_snapshot_20261011` and first preappend snapshot are archival and are not used by the proposal.

The existing pair-axis conclusion `21_PAIR_AXIS_TICKET_BUDGET.md`, along with topics 12, 19, and 20, is explicitly pinned in the snapshot. The snapshot also hashes every other central file, so the future compare-and-swap must reject any added, removed, or changed central file. All existing topic documents must remain byte-identical.

## Future narrow write set

If the completed A/C artifacts and a final publication payload receive root approval, a later append may create one new numbered conclusion and replace only these four central indexes: `README.md`, `SOURCES.md`, `research_register.json`, and `source_manifest.json`. It must preserve every old topic document and every old source-manifest row, append only the approved study rows and new central document, and update only the approved latest-study metadata. The pair-event claim must remain distinct from exact Top2, complete Top3 combinations, and ticket probability. Publication must not imply operational promotion or independent future validation.

`guarded_append_skeleton.py` separates proposal preparation from apply. `--prepare` validates final A/B/C manifests and the frozen Markdown payload, then writes a five-file proposal only under this B folder. `--apply` rebuilds and verifies that exact proposal, checks root approval against the payload, source-pin set, snapshot, and complete change-set hashes, then applies only the four index files plus the one new conclusion. It also checks that every prior central file still matches the snapshot and that every numbered topic remains unchanged.

`publication_manifest.json` pins the final A, B, and C manifests, the conclusion payload, and the fresh snapshot. Its root approval remains false. Running `--prepare` writes a proposal only under this B folder; no central file has been written. Any later central apply requires root's explicit approval of the exact payload, source-pin set, snapshot, and complete change-set hashes.

## Checks

From the repository root, a future refresh first captures a fresh snapshot with a new label, then updates the snapshot pin in `publication_manifest.json` before preparing a new proposal:

```sh
.venv/bin/python jeju/research/20261011_pair_top3_direct_design_v1/publication_preparation/guarded_append_skeleton.py --capture-snapshot preappend_YYYYMMDD
.venv/bin/python jeju/research/20261011_pair_top3_direct_design_v1/publication_preparation/guarded_append_skeleton.py --prepare
```

Review the generated `prepared_append/` hashes and have root approve the exact payload, source-pin set, snapshot, and change-set hashes. Only a later, separately authorized run may use `--apply --confirm-append pair_top3_direct_20261011`. Until that authorization exists, keep central files read-only. If any CAS or protected-topic check fails, stop and capture a new snapshot after confirming the current central state. Never restore a preparation snapshot over central files.
