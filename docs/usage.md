# Using Context Keeper

Context Keeper is an Agent Skill. Its `SKILL.md` tells a coding agent how to find a project's saved context, retrieve the records relevant to a task and maintain those records without losing history. Its bundled Python helper performs the storage, lookup and brief-generation commands.

## Use it with your coding agent

First [install the skill](../README.md#install-the-skill) in your agent's skill directory and follow that agent's discovery procedure. Then give it a request such as:

> Use context-keeper to resume this project. Find its existing context store, retrieve the decisions relevant to the parser trial and flag anything that needs review.

The agent reads the skill instructions and uses its helper commands as needed. Its response should identify the relevant context and any source or coverage problems. The skill does not automatically capture your entire conversation; the saved records come from selected project documents or explicit additions by the authorized writer.

## Run the helper commands directly

The rest of this guide shows the Python commands behind the skill. You can run them yourself or inspect them to understand what your agent is doing.

Start with [project-store setup](../README.md#set-up-a-project-store-manually) if no installation exists. For an existing project, read its instructions to find the store and its maintenance owner. Several projects may use a shared installation; an absent local folder does not mean you should create a new store.

## Terms used by the tool

| Term | Meaning |
| --- | --- |
| Record | One saved decision, rule, fact, question, note or piece of project state. It has an ID so you can inspect or update it. |
| Source | The document or reference a record came from. Checked file sources also identify where that file lives. |
| Scope | A label for an area of work, such as `review` or `build`. You choose these labels when saving context. |
| Brief | The handoff generated for a task, with source links and a report of what was included or omitted. |
| Writer | The person or agent authorized by the project to change the store. Other agents can retrieve context and report issues. |

The commands below use the practice project from the README. Substitute your project's actual runner path and scopes.

## Resume a task

Tell Context Keeper what you are about to do:

```text
python -X utf8 my-project/.context-keeper/ck.py brief "implement the parser trial" --output-budget 6000 --output .context-keeper/briefs/parser-v2.md
python -X utf8 my-project/.context-keeper/ck.py check .context-keeper/briefs/parser-v2.md
```

Read the saved brief before starting work. Give it to the agent continuing the task by sharing the file or through your host's supported context workflow. Context Keeper itself does not inject it into every chat.

If a project stores separate areas of work, repeat `--scope` to include the ones this task needs:

```text
python -X utf8 my-project/.context-keeper/ck.py brief "resume the adapter trial" --scope review --scope build --output-budget 6000 --output .context-keeper/briefs/adapter-v1.md
```

Those labels must match the context saved in your project. Leaving out `--scope` considers all scopes. Global context is also considered by default. A writer can mark a verified project-wide rule as mandatory so it applies across scopes.

## Find out why a decision was made

Search the current records, then inspect the ID shown in the results:

```text
python -X utf8 my-project/.context-keeper/ck.py search "parser"
python -X utf8 my-project/.context-keeper/ck.py show 1
```

`show` returns the exact record, its source, current status and change history. Follow the source to read the surrounding explanation. Search uses word matching, so try another term or consult the governing document if the result is incomplete.

## Bring in a project update

The writer reviews the changed documents, then previews what an import would do:

```text
python -X utf8 my-project/.context-keeper/ck.py ingest --dry-run
```

When ready to save the imported context:

```text
python -X utf8 my-project/.context-keeper/ck.py ingest
python -X utf8 my-project/.context-keeper/ck.py reconcile --json
```

Review the reported changes, near-duplicates, missing sources and capture limits. Importing a revised document does not automatically authorize its new instructions or retire an old decision. Correct or retire records only after checking what the project actually decided.

For example, after a verified change from a seven-day to a fourteen-day retention rule, the writer can correct the original record using its actual ID:

```text
python -X utf8 my-project/.context-keeper/ck.py correct 2 "Retain raw inputs for 14 days." --reason "Reviewed the approved retention change"
```

Record `2` is only an example. The command keeps the original in history and links its replacement. If import already captured one matching replacement from the same source, kind and scope, the correction reuses it. Conflicting existing history or ambiguous matches require review rather than an automatic merge. Use `show` to read back the result, then generate a new brief with a new filename.

If a change affects only part of a decision, retain the valid earlier clauses: save the precise new ruling and link the records with `amend`. The [command reference](../skills/context-keeper/references/commands.md) explains partial amendments and explicit source acknowledgments.

## Read the handoff's status

`FRESH` means its checked inputs are unchanged and have no unresolved source issue. It does not tell you whether an author had approval authority or whether every relevant document was supplied.

`INCOMPLETE` means something required could not be included or resolved. Read the explanation before acting. Context Keeper keeps records and linked amendments whole, so a required group that cannot fit is disclosed rather than cut mid-sentence.

The coverage section also lists ordinary omissions. A brief can pass its checks while still leaving out lower-ranked context to fit the requested size. Increase the allowance, narrow the task, or inspect the omitted sources as needed. `--require ID` includes a known essential record and its linked amendments or makes the brief explicitly incomplete.

Two controls affect size: `--budget` limits the selected record text, while `--output-budget` limits the whole exported Markdown, including source links and status information. Both use characters.

## Know which actions change data

Search, readback, status, brief generation, freshness checks, reconciliation reports and import previews open the store read-only. Saving a brief creates only the requested new output file.

Imports, new records, corrections, retirements, amendments, source acknowledgments and migration apply change the store and belong to its designated writer. Follow the owning project's procedures. Installing or invoking the tool does not give an agent permission to override them.

For automation, these exit codes distinguish a successful operation from a result that needs attention:

| Operation | Exit codes |
| --- | --- |
| `brief` | `0`: produced without required-context issues; `1`: incomplete review artifact; `2`: invalid input, incompatible store or a size limit too small to produce the output |
| `check` | `0`: checked inputs unchanged with no unresolved issues; `1`: stale or incomplete; `2`: invalid or missing input |
| `reconcile` | `0`: clear; `1`: issues or review leads; `2`: invalid input |
| Generated runner | `75`: a `.maintenance` flag beside the runner blocks access before the database is opened |

For source configuration and the complete selection and freshness behavior, continue to the [command reference](../skills/context-keeper/references/commands.md). Existing installations have a separate [migration and recovery guide](migration.md).
