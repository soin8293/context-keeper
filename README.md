# Context Keeper

Context Keeper is an [Agent Skill](https://agentskills.io/home) that teaches a coding agent how to save, retrieve and update project context between sessions.

The agent reads the instructions in [`SKILL.md`](skills/context-keeper/SKILL.md) and uses the bundled Python scripts to store decisions, look up current instructions and prepare a brief for its next task.

Maintained by [AmirahCo](https://www.amirahco.us/).

[![Checks](https://github.com/soin8293/context-keeper/actions/workflows/checks.yml/badge.svg)](https://github.com/soin8293/context-keeper/actions/workflows/checks.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## How the agent uses it

Install the `skills/context-keeper/` folder in your coding agent's skill directory. Its name and description tell a skills-compatible agent when to load the full `SKILL.md` instructions. You can also ask your agent to use Context Keeper explicitly. Skill discovery and invocation follow your agent's own interface.

For example, ask:

> Use context-keeper to resume work on the adapter trial. Find this project's existing context store and retrieve the decisions and restrictions relevant to that task.

The skill instructs the agent to find the existing store, retrieve the relevant records, check their sources and report missing or outdated context. When an authorized decision changes, it tells the project's designated writer how to update the record while preserving the earlier version.

Here, **project context** means saved decisions, constraints and current state: for example, “use synthetic data for the trial,” “the builder owns this task,” and “keep the report local until publication is approved.” The [example brief](examples/expected-handoff.md) shows these instructions together with links to their sources.

The [usage guide](docs/usage.md) explains agent invocation and the helper commands behind this workflow.

## How it fits into your project

`skills/context-keeper/` is the installable skill folder. `SKILL.md` contains the agent's instructions, `references/` contains detailed command and upgrade guidance, and `scripts/` contains the Python helper and installer. The agent loads or runs those resources as the task requires.

Each project keeps its saved context in a local SQLite database. The Python helper imports decisions, rules and status entries from selected Markdown documents, retains source references and history, and writes task briefs as Markdown. It can also save a verified decision directly.

It does not automatically read every chat or attach itself to every agent. The project documents, configured sources and maintenance procedure determine what it knows. Installing the skill and setting up a project's store are separate steps.

## Install the skill

Clone the repository, then install `skills/context-keeper/` into the skill directory used by your coding agent:

```text
git clone https://github.com/soin8293/context-keeper.git
cd context-keeper
python -X utf8 -m pip install -r requirements-dev.txt
python -X utf8 scripts/skills.py install context-keeper --target-root /path/to/agent/skills
```

Replace `/path/to/agent/skills` with your agent's actual skill directory. The installer copies the skill folder, checks earlier installation receipts, keeps external backups and refuses to overwrite local edits.

Make the installed skill available through your agent's normal discovery or reload procedure, then use the example request above. Installing these instructions does not create a project's database or upgrade an existing project's Python runner; those are separate steps covered by the skill.

## Requirements

**Early release: v0.4.1.** Use a coding agent that supports Agent Skills and can read project files and run Python. The bundled helper needs Python 3.11+ and a local writable project directory. Each store has one designated writer.

The Python helper uses the standard library and makes no model or network calls. Your coding agent runs in its usual host and model environment.

Windows and Linux are exercised in CI with Python 3.11 and 3.12. Other hosts and agent integrations may work but are not covered by that matrix. The runtime and project installer have no third-party Python dependencies. The optional skill installer and development checks use PyYAML from [requirements-dev.txt](requirements-dev.txt).

## Set up a project store manually

The skill guides the agent through project setup when authorized. These commands show the same helper workflow directly, using a practice project. If you have not already cloned the repository:

```text
git clone https://github.com/soin8293/context-keeper.git
cd context-keeper
```

From the repository root, create the practice project:

```text
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

## Try the Python helper demo

To see a fuller handoff with decisions from several areas of work, run the supplied fictional project from the repository root:

```text
python -X utf8 examples/demo.py demo-work --prepare-only
python -X utf8 examples/demo.py demo-work
```

The first command creates the example project and its store. If your host requires a database overview or review of its notes, do that before the second command. The demo saves a complete handoff, a deliberately incomplete handoff with a small space allowance, and a result summary in `demo-work/`. It also checks that changing a source makes the earlier handoff stale and that a query leaves the database unchanged. It refuses to reuse an unrelated directory.

See [the fixture](examples/project/), [expected handoff](examples/expected-handoff.md) and [testing evidence](docs/testing.md).

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

[MIT](LICENSE). Context Keeper and its installation/testing helpers are maintained by `soin8293` through AmirahCo. This release contains the skill, its Python helpers, fictional examples and documentation. Private project databases, conversations and operational records are excluded. Python and optional development dependencies retain their own licenses. No SkillOpt, Harness², AODB or model-provider implementation is bundled.

## AI assistance

AI tools assisted implementation, regression tests and documentation. The maintainer, `soin8293`, is responsible for project decisions and for reviewing and validating contributions. The documented checks describe what was exercised; AI assistance does not establish correctness, security or production readiness. Existing licenses and contributor credits remain applicable.
