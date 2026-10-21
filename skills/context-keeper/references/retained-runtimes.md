# Retained runtimes and migration

Use for older/custom installations, shared stores or a read-only audit. Installed skill bytes and a retained project runner can differ. Preserve the actual runner, store, writer ownership and saved briefs until its capability and migration boundary are clear.

- Inspect the existing runner/help/receipts; use `capabilities` only when supported. v0.4/schema v2 uses read-only SQLite connections for queries and dry runs. Older runners may initialize or migrate from the query constructor; use the host's read-only route under a strict audit boundary.
- Retained unanchored runners need an explicit absolute existing --db before the subcommand. Current packaged runners anchor to the project. Use UTF-8 process output; a display failure after a write needs state readback before retrying.
- Numeric IDs are required by mutations; D42 means 42. `check` takes a saved brief path. Older STALE output has returned exit 0, so inspect the actual implementation rather than assuming current exit contracts.
- A current/checked record is not proof of current authority. Compare the governing source passages and preserve partially valid earlier clauses. Do not replace the project's retrieval/coordination tools merely because a context lookup is incomplete.

## Explicit schema/origin migration

New reads never initialize or migrate an existing store. Incompatible schema yields an actionable error. Runtime installation also refuses to migrate an existing database implicitly.

```text
python -m contextkeeper --db ABSOLUTE_EXISTING_DB migrate
python -m contextkeeper --db ABSOLUTE_EXISTING_DB migrate --origin-map reviewed-origins.json --apply
```

Preview is read-only. The map is an explicit JSON object from source IDs to actual existing ingestion roots, for example `{ "12": "PROJECT/docs/review" }` with resolved real paths in the owner's private file. A common `--source-root ROOT` maps unmapped sources only when the writer has verified they truly share that origin. Relative refs do not establish their original root; leave ambiguous sources unmapped and visibly unresolved. Per-ID mappings are needed when the old store mixed roots. Do not guess all refs came from the database's parent project.

Apply requires writer authority, validates mappings, saves an SQLite-consistent adjacent `.backup-<token>` database and makes additive schema changes in a transaction. It preserves records/status/history and adds source origins, explicit mandatory policy, amendment links and source-scan metadata. No canonical business database is supported. Use one writer and stop concurrent readers/writers for a controlled migration. An unresolved source is retained as unknown, not deleted or assigned a guessed path.

Rollback: stop database users; preserve the failed/upgraded store and its WAL/journal files together, restore the verified backup at the exact original database path, restore the compatible old runtime/router receipt from its external backup, then verify read-only status/history. Do not overwrite an active SQLite database or leave an upgraded WAL beside a restored older main file. The backup is a logical SQLite snapshot; its file-header bytes may differ from the original.

An unreceipted legacy project still needs explicit adoption/reconciliation before the runtime installer can replace code. Package deployment alone does not update that project's live runner/store. Rebuild old briefs after an intentional schema/hash upgrade; old inline fingerprints remain parseable but have full-store semantics. A portable brief needs its matching store/source roots to check freshness; missing roots are unresolved.

## Reviewed legacy runtime adoption and shared callers

Use `python scripts/install.py inspect-legacy PROJECT --output NEW_EXTERNAL_RECEIPT` to record current code/router/runner hashes without opening the database. Review those source files and existing writer ownership before adoption; matching hashes establish integrity, not trust. After a separately approved schema migration, preview/apply `project PROJECT --adopt-receipt NEW_EXTERNAL_RECEIPT --no-ingest`, adding `--shared-runner` when an existing shared runner must retain caller-relative source/output paths. Receipt files must stay outside the context directory; later local edits and an existing receipt cannot be bypassed by re-adoption.

A shared runner pins its adjacent database by default, honors an explicit global --db, and preserves caller cwd for ingest/output. Normal project runners anchor cwd. Recognized updates preserve the selected mode. `.maintenance` beside a generated runner blocks it with exit 75 before import/database access. Older unguarded runtimes must have their writers paused explicitly; merely adding that flag does not change old code. Never remove another operator's maintenance flag.

Migration preview/apply includes row counts and hashes of original record, history, source and event fields, without exporting their contents. Compare matching original column sets before/after; a newly introduced checked column can change the source hash shape in very early stores. This verifies retained data, not source authority or semantic reconciliation.
