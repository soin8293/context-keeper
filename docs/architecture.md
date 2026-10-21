# Architecture

Context Keeper is a local Python CLI over a project-owned SQLite store. The reusable skill tells an agent how to locate the owning store, retrieve a bounded task packet and route maintenance through the authorized writer.

## Components

| Component | Responsibility |
| --- | --- |
| [store.py](../skills/context-keeper/scripts/contextkeeper/store.py) | Record/source storage, retained history, explicit corrections and amendment relationships; read-only schema checks and migration preservation manifests |
| [ingest.py](../skills/context-keeper/scripts/contextkeeper/ingest.py) | Bounded Markdown discovery, extraction, deduplication, source drift and writer acknowledgments |
| [brief.py](../skills/context-keeper/scripts/contextkeeper/brief.py) | Task ranking, whole-group packing, source citations, coverage and complete-output limits |
| [freshness.py](../skills/context-keeper/scripts/contextkeeper/freshness.py) | Scoped record/source fingerprints and actionable source issues |
| [cli.py](../skills/context-keeper/scripts/contextkeeper/cli.py) | Read/write command boundaries, arguments, structured readback and exit codes |
| [project installer](../skills/context-keeper/scripts/install.py) | Preview/apply, guarded runtime updates, legacy receipt inspection/adoption and generated runners |
| [skill installer](../scripts/skills.py) | Copies the named self-contained skill with receipts, external backups and local-edit guards |

## Data flow

1. The writer selects governing Markdown and configures active paths/limits if defaults do not fit.
2. Ingestion extracts candidates and records their relative reference plus explicit origin root and scope. It reports near-duplicates, caps and stale sources rather than silently deciding authority.
3. Verified corrections add a new record and supersede the old one. A partial override links both records without discarding valid earlier clauses.
4. Retrieval selects scope sets and global policy, expands required amendment dependencies, ranks task context and packs whole groups.
5. The brief contains source links, status/omissions, a record budget and complete-output cap, plus compact freshness metadata.
6. A later check compares the declared candidate/source boundary and reports stale or incomplete context without modifying the database.

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
