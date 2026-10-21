# Architecture

Context Keeper is an Agent Skill packaged in `skills/context-keeper/`. The coding agent reads `SKILL.md` for the workflow and runs bundled Python scripts to save, retrieve and update project context. This page describes that skill package and the helper implementation.

This page explains the implementation. Start with the [usage guide](usage.md) for everyday operation.

## From project notes to a handoff

The original documents explain what the project decided. Context Keeper saves individual entries from those documents in a local SQLite store, with links back to their sources. The store tracks which entries are current and which were replaced or retired.

When an agent resumes work, the Python command-line tool selects context for that task and exports a Markdown brief. Its size allowance keeps the handoff manageable; its coverage section shows what was left out. A later check can detect changes to the saved context or the source files.

The skill instructions govern how the agent uses this helper: locate the existing store, retrieve task context, inspect sources and omissions, and leave updates to the authorized writer. The host determines how the skill is discovered and how the brief reaches the agent.

## Components

| Component | Responsibility |
| --- | --- |
| [SKILL.md](../skills/context-keeper/SKILL.md) | Agent instruction entrypoint: when to use Context Keeper and how to retrieve and maintain the project's context |
| [references](../skills/context-keeper/references/) | Detailed helper commands, source-selection behavior and retained-runtime upgrade instructions, loaded when needed |
| [store.py](../skills/context-keeper/scripts/contextkeeper/store.py) | Record/source storage, retained history, explicit corrections and amendment relationships; read-only schema checks and migration preservation manifests |
| [ingest.py](../skills/context-keeper/scripts/contextkeeper/ingest.py) | Bounded Markdown discovery, extraction, deduplication, source drift and writer acknowledgments |
| [brief.py](../skills/context-keeper/scripts/contextkeeper/brief.py) | Task ranking, whole-group packing, source citations, coverage and complete-output limits |
| [freshness.py](../skills/context-keeper/scripts/contextkeeper/freshness.py) | Scoped record/source fingerprints and actionable source issues |
| [cli.py](../skills/context-keeper/scripts/contextkeeper/cli.py) | Read/write command boundaries, arguments, structured readback and exit codes |
| [project installer](../skills/context-keeper/scripts/install.py) | Preview/apply, guarded runtime updates, legacy receipt inspection/adoption and generated runners |
| [skill installer](../scripts/skills.py) | Copies the named self-contained skill with receipts, external backups and local-edit guards |

## Data flow

1. The writer chooses which project documents supply context. Optional source configuration controls paths and import limits.
2. Import saves entries with their document reference, location and area-of-work label (scope). It reports similar entries, limits and changed sources for review.
3. A verified correction links an old record to its replacement, keeping the original. It can reuse a matching replacement already imported. A partial change links both instructions so valid earlier clauses remain available.
4. A brief request selects the relevant scopes and ranks their context for the task. Required records and linked amendments stay together.
5. The exported brief includes source links, status and omissions. Separate limits control selected text and the complete output, including its supporting information.
6. A later check compares saved fingerprints of records and source files. It reports changes or unresolved issues without updating the database.

## Schema and history

Schema v2 has seven tables: `meta`, `source`, `record`, `record_history`, `event`, `amendment` and `source_scan`. Source rows retain reference/checked-state/origin metadata. Records retain kind, scope, status, predecessor/successor links, source ID and timestamps. An explicit `mandatory` flag marks verified policy applicable across scope boundaries.

`correct` preserves the original row and its history. `retire` changes current status while retaining the row. `amend` records the affected clause/relationship, keeping both rows available. Retrieval follows correction chains to current amendment endpoints while preserving historical links. A retired required endpoint is a visible unresolved condition.

There is no automatic semantic conflict solver or approval detector. A word such as SUPERSEDED can be a review lead; it is not a command to delete or retire data.

## Reads and writes

Read commands and ingestion dry runs use SQLite URI `mode=ro` plus `query_only`, validating schema without DDL/migration. Missing or incompatible stores fail instead of becoming empty databases. Brief export writes only the requested new artifact.

Initialization, ingestion, record changes, source acknowledgments and migration apply are explicit writer operations. Use one designated writer. The project sidecar records the supported route; runtime invocation does not create authority to change another project's canonical data.

The normal generated runner anchors cwd to its project. Explicit shared-runner mode instead preserves the caller's source/output cwd and pins the shared database beside the runner, while honoring a global explicit `--db`. A `.maintenance` flag blocks generated runners before import/database access. It does not stop older unguarded code or arbitrary other SQLite clients.

## Budgets and selection

`--budget` counts selected record text. `--output-budget` counts complete Markdown, including metadata and source links. Groups are removed whole when formatting overhead exceeds the cap. An unfit required group makes the artifact INCOMPLETE; impossible metadata/detail caps fail rather than truncate.

Scopes can be repeated. Globals are candidates by default; the global policy can filter them explicitly, while writer-marked mandatory policy always applies. Coverage distinguishes scope/policy exclusions from budget omissions. An omission is not evidence of absence.

## Freshness boundary

V2 stores compact scoped digests rather than embedding the full-store record inventory. Candidate dependencies include relevant omitted records, bindings, policy and amendment relationships. Foreign-scope manual additions do not invalidate a scoped packet. Freshness conservatively checks the in-scope/global candidate pool before relevance filtering.

Declared source bytes and selection configuration participate in source fingerprints. Missing roots, unknown origins, unrecorded candidates, skipped required sources and uncaptured changes remain visible. Legacy inline snapshots retain full-store semantics and may need regeneration after an upgrade.

FRESH means these declared checks passed. It does not prove that a decision is true, that its author had approval authority, that the whole corpus was reviewed, or that an agent is currently running.

## Operational limits

The supported boundary is local storage and one writer. Concurrent correction stress, distributed locks, hostile schemas and arbitrary WAL/backup combinations are not certified by the synthetic suite. Keep a consistent backup and use [controlled migration/recovery](migration.md). The [testing guide](testing.md) separates automated checks from unsupported general claims.
