# Commands, selection and freshness

The maintained package contains runtime v0.4.1/schema v2, an explicit project installer and synthetic tests. The separately recovered v0.3.0 source remains preserved. Python 3.11+ and the standard library suffice. No original private project data is bundled.

The project runner anchors cwd to the project. Direct use also works from `scripts` with `python -m contextkeeper --db ABSOLUTE_DB COMMAND`. Global --db precedes the subcommand.

```text
python PROJECT/.context-keeper/ck.py capabilities
python PROJECT/.context-keeper/ck.py ingest --dry-run
python PROJECT/.context-keeper/ck.py ingest --scope build
python PROJECT/.context-keeper/ck.py brief "adapter task" --scope review --scope build --require 12 --budget 6000 --output-budget 12000 --output .context-keeper/briefs/task-v2.md
python PROJECT/.context-keeper/ck.py check .context-keeper/briefs/task-v2.md
python PROJECT/.context-keeper/ck.py reconcile --scope build --json
python PROJECT/.context-keeper/ck.py add constraint "Never publish private credentials" --mandatory
python PROJECT/.context-keeper/ck.py add decision "Use the selected adapter" --scope build --source DECISIONS.md --source-checked --source-root PROJECT
python PROJECT/.context-keeper/ck.py correct 12 "Verified replacement decision" --reason "source revision"
python PROJECT/.context-keeper/ck.py amend 12 15 --reason "Only the upload clause changes; retention stays valid"
python PROJECT/.context-keeper/ck.py retire 12 --reason "verified obsolete"
python PROJECT/.context-keeper/ck.py search "adapter" --scope review --scope build
python PROJECT/.context-keeper/ck.py show 12
python PROJECT/.context-keeper/ck.py status --scope build
python PROJECT/.context-keeper/ck.py log
```

Queries and dry runs use URI mode=ro plus query_only, validating schema without DDL/migration. Writer commands own only this derived context store. Missing/incompatible stores return 2. Brief export refuses an existing name. `brief` returns 1 if required records, amendment endpoints or source issues make it incomplete, and may still save that explicitly marked review artifact. Ordinary budget omissions remain disclosed and do not imply full coverage. `reconcile` returns 1 for issues or unresolved change-word leads, 0 when clear; words are review leads rather than automatic truth/status changes.

## Source selection

Create project-owned `.context-keeper/sources.json` only when defaults do not fit:

```json
{
  "active": ["docs/current-rulings.md", "AGENTS.md"],
  "include": ["governance/*.md"],
  "exclude": ["docs/archive/*"],
  "max_files": 200,
  "max_items": 200,
  "max_file_bytes": 1048576
}
```

Active paths/globs run first, then extra includes, priority root files, remaining root Markdown, and decisions/doc/docs/planning/research/sources directories. Includes extend discovery; exclusions remove candidates. Paths remain within the declared ingestion root. Explicit missing paths, outside-root links, read/UTF-8 failures and caps are reported. CLI --max-files/--max-items/--max-file-bytes override configured defaults for that ingest; keep durable required limits in configuration so later checks use the same selection. Excluded/generated files are disclosed but not unresolved maintenance failures.

Capture includes bullets, content tables and ordinary paragraphs only under explicit decision/constraint/state headings. It preserves multi-line paragraphs and wrapped bullets, excludes fenced code, blockquotes/navigation and generated briefs, and reports caps across all record types. Blank-separated table data stays available; following delimiter rows identify new headers. General narrative is deliberately outside heuristic extraction. Source-file byte fingerprints still detect uncaptured edits.

Record identity during ingestion includes kind, text, exact source ref, origin root and scope, across every status. Retired/corrected originals cannot resurrect in that identity. Same-scope/root near-duplicates are reported without automatic acceptance, including changed numbers. No wording/date inference decides approval. Checked sources without an explicit origin remain unresolved.

After a raw change adds no captured item, ingestion records an unresolved source review. Inspect that revision, reconcile verified changes, then explicitly acknowledge if appropriate:

```text
python PROJECT/.context-keeper/ck.py reconcile --acknowledge-source DECISIONS.md --project-root PROJECT --scope build --reason "Reviewed exact revision; narrative change does not alter the stored ruling"
```

This acknowledgment refuses a source changed again since ingestion. It does not correct stale records, accept suppressed candidates or remove other issues.

## Packet contract

Repeat scopes to select related areas. `--globals all` includes global candidates; relevant project records win priority over unrelated globals. `relevant` filters unmatched nonmandatory globals; `exclude` omits them. Explicit mandatory policy always applies. Required IDs and connected partial-amendment groups are packed together across scope boundaries; current status is shown and retired linked endpoints make the packet incomplete. Ordinary scope exclusions and budget omissions have separate counts.

Record budget and complete-output cap are distinct. Whole groups are removed in priority order when citation/format overhead exceeds the output cap. Required omissions are marked INCOMPLETE; impossible metadata/detail caps fail with an actionable error rather than truncating. Default complete cap is 16,000 characters. --full-omitted can require a larger cap.

V2 embeds fixed-size scoped record/source digests plus selection metadata, instead of the full store inventory. Relevant candidate, source binding, amendment, policy, source-byte or source-selection changes invalidate freshness, including omitted candidates. Foreign-scope manual additions do not invalidate a scoped packet. Checks recompute sources from persisted explicit origins, and report missing roots/uncaptured changes/unknown origins. Local source roots must remain available; copying a brief alone does not recreate its store or source authority. Legacy inline mappings still parse and compare full-store hashes; regenerate once after schema/hash changes. Detailed actionable diagnostics live in reconcile output, not an obligatory sidecar.

Freshness is a record/source consistency check. It does not establish semantic truth, automatic corpus completeness, concurrent writer safety or live agent status. One writer and project governance remain required.

Legacy inspection/adoption and shared-runner mode are covered in [retained runtimes](retained-runtimes.md). A generated runner pauses with exit 75 when its adjacent .maintenance file exists. This does not stop older unguarded code or unrelated database clients. Runtime upgrades do not perform historical content reconciliation.
