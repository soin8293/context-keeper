# Testing and evidence

Context Keeper includes agent instructions and a Python helper. The automated checks validate the skill package's structure and the helper's behavior: saving context, retaining decision history, generating briefs and detecting changes. They do not run a coding agent through every instruction or certify host-specific skill discovery.

Tests use temporary fictional projects, and the demo runs the actual installed project tool. This page explains how to repeat the checks and where their coverage ends.

## Run the checks

```text
python -X utf8 -m pip install -r requirements-dev.txt
python -X utf8 scripts/skills.py check
python -X utf8 scripts/check_release.py
python -X utf8 scripts/skills.py test
python -X utf8 examples/demo.py demo-work --prepare-only
python -X utf8 examples/demo.py demo-work
```

Use a fresh demo directory. If your host requires a database overview/notes check, perform it after prepare-only. Runtime tests use temporary synthetic stores through their owning engine.

## Covered behavior

The Context Keeper suite contains 110 tests, covering the core retained-history workflow and targeted capture/retrieval/upgrade regressions. Shared installer tests separately exercise local-edit refusal, both Windows directory-rename failure points, verified external backups and rollback after failed transfers.

| User expectation | What the tests exercise |
| --- | --- |
| Earlier decisions remain inspectable | Corrections and retirements preserve records and history; partial changes retain both applicable instructions. |
| Project notes can become usable context | Decision paragraphs, lists and tables are captured across the tested formatting cases, with visible import limits and repeat-import behavior. |
| Similar files remain distinct | Source locations and scopes stay separate; changed numbers and similar wording are reported for review. |
| The handoff fits without hiding required context | Whole records and amendment groups stay intact, required omissions are marked incomplete, and the complete export respects its size limit. |
| Changes are noticed | Record, source-file and source-configuration changes affect freshness; unrelated out-of-scope records do not change the tested scoped fingerprint. |
| Reading context leaves the store unchanged | Queries and previews use read-only connections, and missing or incompatible stores fail instead of being created or migrated. |
| An upgrade retains the existing project | Preservation hashes, guarded installation receipts, maintenance blocking and shared-runner path behavior are checked. |

The demo exercises the actual project runner and generated artifacts. It checks normal freshness, expected incomplete output under a tight budget, source drift and unchanged DB bytes during a query. The [display example](../examples/expected-handoff.md) uses normalized paths; regenerate locally for a checkable live packet.

## Documentation and release checks

`check_release.py` applies the existing publication-workspace Markdown-audit approach to this standalone tree: empty content, unresolved template markers, local links/anchors, machine paths and accidentally included data files. Tests include deliberately broken fixtures so the check cannot pass merely because it ran.

GitHub CI runs on Linux/Windows and Python 3.11/3.12. A green check applies to its exact commit; see the [workflow](../.github/workflows/checks.yml). It is not a substitute for inspecting the release archive, links, rights, private data or real deployment behavior.

## Limits

Synthetic regressions establish the tested contracts, not universal semantic recall, model adherence or an accuracy percentage. Markdown capture/ranking remains heuristic. Source freshness does not prove factual truth or author authority. Automatic host discovery, concurrent writers, hostile SQLite schemas, arbitrary WAL recovery and distributed operation are not certified by this suite.

Record actual failures and a synthetic reproduction when a new edge case appears. Preserve positive controls and keep exposed development cases separate from any later unseen evaluation.
