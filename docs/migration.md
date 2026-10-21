# Migration and recovery

Use this guide when updating the Context Keeper Agent Skill or the Python helper already installed in a project. The saved decisions and history belong to the project's database and must be retained. New projects can follow [project-store setup](../README.md#set-up-a-project-store-manually).

There are two installations to keep track of. The **skill folder** contains `SKILL.md`, references and scripts for the agent to use. The **project runtime** is a retained copy of the Python helper beside the project's database, usually invoked through `.context-keeper/ck.py`. Updating the skill folder alone leaves that project code in place.

First find the runner and database the project actually uses, including any shared installation. Keep its writer ownership, source locations and history. The steps below let you inspect the old store, review any required schema changes, update its code and verify the retained data before resuming work.

Schema changes update the database's structure. They do not decide which historical instructions are still valid; reviewing those decisions is a separate maintenance task.

## Preview without changing data

Use the new source runtime from its scripts directory; do not invoke an old query constructor merely to discover its behavior:

```text
cd skills/context-keeper/scripts
python -X utf8 -m contextkeeper --db /absolute/path/to/context.sqlite migrate
```

Preview opens SQLite read-only, reports additive schema changes and unresolved source origins, and returns row counts/hashes of original data/history fields without exporting their contents. Follow any host-required database overview/notes procedure first. Missing/incompatible/future schemas fail rather than silently downgrade.

The command examples use an explicit existing database path. Resolve the actual path for your project before running them.

## Review source origins

Older records may name a source such as `DECISIONS.md` without saving the directory it came from. If several projects have that filename, Context Keeper needs the original directory to check the correct file. This is the source's origin root.

Prepare a private JSON object mapping reviewed source IDs to their actual existing roots. A root must come from project evidence, not the database's location or a guessed common directory.

Use `--origin-map reviewed-origins.json` for mixed roots. `--source-root` maps unmapped sources to one common root only when the writer has verified that common origin. Leave ambiguous or missing roots unknown; preservation is preferable to invented provenance.

## Apply under controlled maintenance

Pause the designated writer and other clients. A generated runner honors an adjacent `.maintenance` file with exit 75; old unguarded code needs an explicit operator pause. Do not remove another operator's flag.

```text
python -X utf8 -m contextkeeper --db /absolute/path/to/context.sqlite migrate --origin-map reviewed-origins.json --apply
```

Apply validates mappings, creates an adjacent SQLite-consistent backup and makes additive schema changes in a transaction. It retains original records/status/history and adds origins, mandatory-policy metadata, amendment links and source-scan state. It does not ingest, retire or semantically reconcile historical decisions.

Compare matching original preservation columns/counts/hashes before and after. Very early stores lacking a checked-source field gain that field; compare like-for-like original columns rather than treating a new column as lost history. A logical SQLite backup may have different file-header bytes from the original.

## Adopt a reviewed legacy runtime

From the repository root, inspect code/router/runner files without opening the database:

```text
python -X utf8 skills/context-keeper/scripts/install.py inspect-legacy existing-project --output reviewed-runtime.json
```

Read the actual source and review ownership. The receipt proves file integrity, not trust. It must be external to the project's context directory and is refused if its new output name already exists.

After the separately controlled schema migration, preview and apply:

```text
python -X utf8 skills/context-keeper/scripts/install.py project existing-project --no-ingest --adopt-receipt reviewed-runtime.json
python -X utf8 skills/context-keeper/scripts/install.py project existing-project --apply --no-ingest --adopt-receipt reviewed-runtime.json
```

Add `--wire-agents` only for approved instruction wiring. Add `--shared-runner` when an existing shared invocation must retain caller-relative source/output paths and use the same pinned database. Normal project runners anchor cwd; shared mode survives recognized updates.

Changed code/router files still fail the guard. An existing receipt cannot be bypassed through re-adoption. Recognized updates use their existing receipt and retain backups. Avoid copying code over a live runtime to evade these checks.

## Verify and resume

Inspect capabilities and status using the upgraded runner. Read back exact retained records/history, review the original-data manifest and create a new bounded handoff. Source gaps may correctly make that packet INCOMPLETE; an upgrade does not make old context current by itself.

Remove only your maintenance flag after verification, then resume the designated writer. Keep the backup, receipt and migration record in the project's private work area. Regenerate old briefs when their fingerprint/schema contract changes.

## Rollback

Stop database users. Preserve the current main database and its WAL/journal files together before restoring anything. Restore the verified consistent backup at the exact original path and restore the matching prior runtime/router/receipt/instructions. Never combine an older main database with a newer WAL.

Do not discard legitimate history appended after the backup. If unexpected writers operated during maintenance, preserve both states and reconcile them first. Additive schema can remain compatible with an old runtime, but that is not permission to claim the upgrade completed without validating the actual reader/writer behavior.
