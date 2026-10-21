# Context Keeper

Keep project decisions, constraints and source-linked context current, then hand an agent a bounded brief for its next task.

Maintained by [AmirahCo](https://www.amirahco.us/).

[![Checks](https://github.com/soin8293/context-keeper/actions/workflows/checks.yml/badge.svg)](https://github.com/soin8293/context-keeper/actions/workflows/checks.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Early release: v0.4.1.** The runtime uses Python's standard library and a local SQLite database. No model, API key, embedding service or network connection is needed for normal operation.

## What it does

- Captures bullets, content tables and governing prose from selected Markdown files.
- Preserves old decisions when a correction supersedes them; partial amendments retain the valid earlier clauses.
- Builds task briefs across explicit scopes, with linked sources, whole-record omissions and a complete-output limit.
- Detects changed records and declared source files without writing to the database during queries or dry runs.
- Reports missing sources, capture limits and unresolved changes for the project's writer to reconcile.

The [synthetic handoff](examples/expected-handoff.md) shows an owner ruling, builder assignment and partial publication override together. Run the [demo](#try-the-demo) to generate and check the actual local artifacts.

## Requirements

- Python 3.11 or newer.
- A local writable project directory for an initialized store.
- One designated writer per store.

Windows and Linux are exercised in CI with Python 3.11 and 3.12. Other hosts and agent integrations may work but are not covered by that matrix. The runtime and project installer have no third-party Python dependencies. The optional skill installer and development checks use PyYAML from [requirements-dev.txt](requirements-dev.txt).

## Quick start

Clone the repository and create a disposable project:

```text
git clone https://github.com/soin8293/context-keeper.git
cd context-keeper
python -X utf8 -c "from pathlib import Path; Path('my-project').mkdir(exist_ok=True); Path('my-project/DECISIONS.md').write_text('## Decisions\nUse a local parser trial before deployment.\n', encoding='utf-8')"
```

Preview project installation, then apply without ingestion:

```text
python -X utf8 skills/context-keeper/scripts/install.py project my-project
python -X utf8 skills/context-keeper/scripts/install.py project my-project --apply --no-ingest
```

Read the generated `.context-keeper/context.agent.json`. Follow any database-governance procedure required by your host before the next commands. Then ingest and build a handoff:

```text
python -X utf8 my-project/.context-keeper/ck.py ingest
python -X utf8 my-project/.context-keeper/ck.py brief "implement the parser trial" --output-budget 6000 --output .context-keeper/briefs/parser-v1.md
python -X utf8 my-project/.context-keeper/ck.py check .context-keeper/briefs/parser-v1.md
```

Normal project runners anchor paths to their owning project. The brief above is saved under `my-project/.context-keeper/briefs/`. Existing output files are never overwritten. Add `--wire-agents` during installation only when you want a marked instruction block added to that project's `AGENTS.md`.

Read the brief's status, sources and omissions. `FRESH` means its declared inputs are unchanged and no checked source issue remains; it is not proof of factual truth or complete project coverage.

## Try the demo

```text
python -X utf8 examples/demo.py demo-work --prepare-only
python -X utf8 examples/demo.py demo-work
```

If your host requires a database overview/notes check, perform it between these commands. The demo uses only supplied synthetic material. It generates a normal handoff and an intentionally incomplete tight-budget handoff, checks source drift, and verifies that a query leaves the database bytes unchanged. It refuses to reuse an unrelated directory.

See [the fixture](examples/project/), [expected handoff](examples/expected-handoff.md) and [testing evidence](docs/testing.md).

## Install the reusable skill

Project installation and skill discovery are separate. To install the self-contained skill folder into a discovery directory used by your agent:

```text
python -X utf8 -m pip install -r requirements-dev.txt
python -X utf8 scripts/skills.py install context-keeper --target-root /path/to/agent/skills
```

Choose the actual discovery directory for your host. The installer copies only `skills/context-keeper`, checks a previous receipt before updates and preserves backups outside discovery. It refuses local edits rather than overwriting them. Windows directory locks use a guarded file-update fallback with rollback; pause consumers during that fallback.

Installing a skill does not automatically wire projects, upgrade retained runners or guarantee automatic skill selection in every agent. The skill entrypoint is [SKILL.md](skills/context-keeper/SKILL.md).

## Common operations

```text
python -X utf8 my-project/.context-keeper/ck.py capabilities
python -X utf8 my-project/.context-keeper/ck.py search "parser" --scope review --scope build
python -X utf8 my-project/.context-keeper/ck.py show 1
python -X utf8 my-project/.context-keeper/ck.py brief "parser work" --scope review --scope build --require 1 --budget 4000 --output-budget 8000
python -X utf8 my-project/.context-keeper/ck.py reconcile --json
python -X utf8 my-project/.context-keeper/ck.py ingest --dry-run
```

The authorized writer uses `add`, `correct`, `retire`, `amend` and ingestion after reviewing source changes. For a partial override, add the precise new ruling and link it with `amend BASE_ID NEW_ID --reason "the affected clause"`; both records remain available. Use `show` to read back the exact text, status, source and history.

`--budget` bounds selected record text. `--output-budget` bounds the complete Markdown, including citations and metadata. Whole amendment groups either fit together or produce an explicit incomplete result. No records are clipped to make a packet appear complete.

See [commands and source configuration](skills/context-keeper/references/commands.md), [architecture](docs/architecture.md) and [migration and recovery](docs/migration.md).

## Exit codes and ownership

| Operation | Meaning |
| --- | --- |
| `brief` | 0: artifact produced without required-context issues; 1: explicitly incomplete review artifact; 2: invalid input, incompatible store or impossible output cap |
| `check` | 0: unchanged declared inputs with no unresolved issues; 1: stale/incomplete; 2: invalid/missing input |
| `reconcile` | 0: clear; 1: issues or review leads; 2: invalid input |
| Generated runner | 75: adjacent `.maintenance` flag blocks access before the database is opened |

Ordinary budget omissions still limit coverage even when `brief` returns 0. Query commands and ingestion dry runs use SQLite read-only connections. Initializing, ingesting, correcting, acknowledging sources or applying migrations are writer operations; the tool does not grant authority to perform them.

## Limits

Markdown extraction and lexical ranking are deterministic heuristics. General narrative, ambiguous authority, contradictory decisions and missing source roots need review. A changed number may be reported as a near-duplicate rather than automatically accepted. Source acknowledgments record a writer's review, not proof of correctness.

This is a local, single-writer context tool. It is not a distributed database, autonomous memory service, dispatcher or semantic truth engine. It does not inject context into every host or reconcile historical decisions automatically. Keep stores, backups and generated briefs private; use synthetic reproductions in issues.

## Development and support

```text
python -X utf8 -m pip install -r requirements-dev.txt
python -X utf8 scripts/skills.py check
python -X utf8 scripts/check_release.py
python -X utf8 scripts/skills.py test
```

The [testing guide](docs/testing.md) explains coverage and remaining limits. See [CONTRIBUTING.md](CONTRIBUTING.md) for changes, [SECURITY.md](SECURITY.md) for sensitive reports and [issues](https://github.com/soin8293/context-keeper/issues) for ordinary bugs/questions. No response-time guarantee is offered.

## License and provenance

[MIT](LICENSE). Context Keeper and its installation/testing helpers are maintained by `soin8293` through AmirahCo. This release contains only the selected tool, synthetic fixtures and public documentation. Private project databases, conversations and operational records are excluded. Python and optional development dependencies retain their own licenses. No SkillOpt, Harness², AODB or model-provider implementation is bundled.

## AI assistance

AI tools assisted implementation, regression tests and documentation. The maintainer, `soin8293`, is responsible for project decisions and for reviewing and validating contributions. The documented checks describe what was exercised; AI assistance does not establish correctness, security or production readiness. Existing licenses and contributor credits remain applicable.
