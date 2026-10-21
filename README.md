# Context Keeper

Context Keeper is a skill that helps AI agents keep track of project decisions and pick up where they left off between sessions.

Maintained by [AmirahCo](https://www.amirahco.us/).

[![Checks](https://github.com/soin8293/context-keeper/actions/workflows/checks.yml/badge.svg)](https://github.com/soin8293/context-keeper/actions/workflows/checks.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## Why it exists

You return to a project, start a new chat, or hand work to another agent. The files are still there, but the reasoning is scattered: what was approved, which approach was dropped, what must stay unchanged, and what happens next. Reconstructing all of that takes time. An old summary can also carry a decision that has since changed.

Context Keeper keeps a local record of that project context, linked to the documents it came from. When you are ready to continue, it builds a short handoff for the task at hand. The handoff shows the selected decisions, their sources, and anything left out or needing review.

When a decision changes, the earlier version stays in the history. You can see both what applies now and how the project got there.

## What using it looks like

Suppose a project is testing a new adapter. The owner approves a trial with synthetic data, assigns the trial to a builder, and later says the report must stay local until publication is approved.

The next agent needs those instructions together. Context Keeper can put them in one handoff, include the later publication restriction, and retain the earlier requirement to keep audit logs. Each item links back to its source so the agent can check the original wording.

See the [example handoff](examples/expected-handoff.md) for the actual output from this scenario.

The everyday workflow is:

1. **Save the project context.** Keep decisions, rules and progress in selected project documents. The person or agent responsible for maintaining the store imports and reviews that material.
2. **Ask for context for a task.** Generate a brief such as “resume the adapter trial,” choosing the relevant areas of the project.
3. **Read and check the handoff.** Give it to the agent continuing the work. Follow its source links and review any omissions or unresolved changes.
4. **Keep it current.** As the project changes, review the affected records, correct what changed, and create a new brief.

The [usage guide](docs/usage.md) walks through those steps and explains the terms used in the commands.

## How it fits into your project

The skill tells an agent how to save project context, find it again and keep it current. It includes a local Python runner that stores the records and generates handoffs. Each project chooses who may update its saved context.

You choose which Markdown documents supply context. The tool can read decisions, rules and status entries written as paragraphs, lists or tables under recognized headings. It keeps them in a local SQLite database alongside their source references and history. You can also add a verified decision directly.

It does not automatically read every chat or attach itself to every agent. The project documents, configured sources and maintenance procedure determine what it knows. Installing the skill and setting up a project's store are separate steps.

## Requirements

**Early release: v0.4.1.** You need Python 3.11+ and a local writable project directory. Use one designated person or agent to write to each store. The runtime uses Python's standard library; normal operation needs no model, API key or network connection.

Windows and Linux are exercised in CI with Python 3.11 and 3.12. Other hosts and agent integrations may work but are not covered by that matrix. The runtime and project installer have no third-party Python dependencies. The optional skill installer and development checks use PyYAML from [requirements-dev.txt](requirements-dev.txt).

## Quick start

Clone the repository and create a disposable project:

```text
git clone https://github.com/soin8293/context-keeper.git
cd context-keeper
python -X utf8 -c "from pathlib import Path; Path('my-project').mkdir(exist_ok=True); Path('my-project/DECISIONS.md').write_text('## Decisions\nUse a local parser trial before deployment.\n', encoding='utf-8')"
```

Preview the installation, then create the project's context store without importing documents yet:

```text
python -X utf8 skills/context-keeper/scripts/install.py project my-project
python -X utf8 skills/context-keeper/scripts/install.py project my-project --apply --no-ingest
```

Read the generated `.context-keeper/context.agent.json` notes and follow your project's database procedures. Then import the practice decision and create a handoff:

```text
python -X utf8 my-project/.context-keeper/ck.py ingest
python -X utf8 my-project/.context-keeper/ck.py brief "implement the parser trial" --output-budget 6000 --output .context-keeper/briefs/parser-v1.md
python -X utf8 my-project/.context-keeper/ck.py check .context-keeper/briefs/parser-v1.md
```

`ingest` imports context from the project documents. `brief` writes a handoff of at most 6,000 characters. `check` tells you whether the checked records and source files have changed or need review.

Open `my-project/.context-keeper/briefs/parser-v1.md` to read the result. New exports need new filenames; existing briefs are preserved. Add `--wire-agents` during installation if you want Context Keeper guidance added to the project's `AGENTS.md`.

For a real project, use its actual directory and check for an existing local or shared installation first. See [migration and recovery](docs/migration.md) when upgrading an existing installation.

Read the brief's status, sources and omissions. `FRESH` means its declared inputs are unchanged and no checked source issue remains; it is not proof of factual truth or complete project coverage.

## Try the demo

To see a fuller handoff with decisions from several areas of work, run the supplied fictional project from the repository root:

```text
python -X utf8 examples/demo.py demo-work --prepare-only
python -X utf8 examples/demo.py demo-work
```

The first command creates the example project and its store. If your host requires a database overview or review of its notes, do that before the second command. The demo saves a complete handoff, a deliberately incomplete handoff with a small space allowance, and a result summary in `demo-work/`. It also checks that changing a source makes the earlier handoff stale and that a query leaves the database unchanged. It refuses to reuse an unrelated directory.

See [the fixture](examples/project/), [expected handoff](examples/expected-handoff.md) and [testing evidence](docs/testing.md).

## Install the reusable skill

Project installation and skill discovery are separate. To install the self-contained skill folder into a discovery directory used by your agent:

```text
python -X utf8 -m pip install -r requirements-dev.txt
python -X utf8 scripts/skills.py install context-keeper --target-root /path/to/agent/skills
```

Choose the actual discovery directory for your host. The installer copies only `skills/context-keeper`, checks a previous receipt before updates and preserves backups outside discovery. It refuses local edits rather than overwriting them. Windows directory locks use a guarded file-update fallback with rollback; pause consumers during that fallback.

Installing a skill does not automatically wire projects, upgrade retained runners or guarantee automatic skill selection in every agent. The skill entrypoint is [SKILL.md](skills/context-keeper/SKILL.md).

## Continue with your own project

The [usage guide](docs/usage.md) explains how to resume a task, find an earlier decision, review a project update and understand a handoff's status. The [command reference](skills/context-keeper/references/commands.md) covers flags and source configuration when you need finer control.

For implementation details, read the [architecture](docs/architecture.md). For an existing installation, use [migration and recovery](docs/migration.md) to retain the store and its history while upgrading the tool.

## Reading a handoff responsibly

A brief is a selected view of the context you supplied. Read its sources, status and omissions before relying on it. It may leave out lower-ranked context to fit the requested length, even when its checks pass.

Capture and task matching use rules and word matching. Some material can be missed. Conflicting decisions, changed wording and missing source files need review by the project's writer. Keep real stores, backups and generated briefs private, and use fictional examples when reporting a problem.

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
