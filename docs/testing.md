# Testing and evidence

The repository runs behavior tests and synthetic end-to-end examples. It does not ship real project stores, private observations, transcripts or provider credentials.

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

The Context Keeper suite contains 106 tests, covering the core retained-history workflow and targeted capture/retrieval/upgrade regressions. Shared installer tests separately exercise local-edit refusal, both Windows directory-rename failure points, verified external backups and rollback after failed transfers.

Coverage includes:

- Current/history separation, whole-record omissions, explicit source semantics and ingestion idempotency.
- Governing prose, blank-separated table data, adjacent headers, backtick/tilde fences, wrapped records and consistent item limits.
- Enforced read-only query paths, missing/invalid input and no accidental schema migration.
- Origin/scope identity, numeric near-duplicate reports, source-byte/config drift and explicit acknowledgments.
- Scope sets, required/mandatory records, partial amendments, correction chains and incomplete dependencies.
- Complete-output caps, source URLs and compact scoped metadata after 1,500 unrelated records.
- Legacy preservation manifests, external receipt inspection/adoption, maintenance gates and shared caller compatibility.

The demo exercises the actual project runner and generated artifacts. It checks normal freshness, expected incomplete output under a tight budget, source drift and unchanged DB bytes during a query. The [display example](../examples/expected-handoff.md) uses normalized paths; regenerate locally for a checkable live packet.

## Documentation and release checks

`check_release.py` applies the existing publication-workspace Markdown-audit approach to this standalone tree: empty content, unresolved template markers, local links/anchors, machine paths and accidentally included data files. Tests include deliberately broken fixtures so the check cannot pass merely because it ran.

GitHub CI runs on Linux/Windows and Python 3.11/3.12. A green check applies to its exact commit; see the [workflow](../.github/workflows/checks.yml). It is not a substitute for inspecting the release archive, links, rights, private data or real deployment behavior.

## Limits

Synthetic regressions establish the tested contracts, not universal semantic recall, model adherence or an accuracy percentage. Markdown capture/ranking remains heuristic. Source freshness does not prove factual truth or author authority. Automatic host discovery, concurrent writers, hostile SQLite schemas, arbitrary WAL recovery and distributed operation are not certified by this suite.

Record actual failures and a synthetic reproduction when a new edge case appears. Preserve positive controls and keep exposed development cases separate from any later unseen evaluation.
