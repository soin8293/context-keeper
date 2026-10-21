# Contributing

Start with the [README](README.md) and [architecture](docs/architecture.md). Open an issue or pull request describing the actual task, observed result and expected behavior. Include Python/OS versions and a minimal synthetic reproduction; exclude private databases, messages, identities, credentials and generated briefs from real projects.

Install development requirements and run:

```text
python -X utf8 -m pip install -r requirements-dev.txt
python -X utf8 scripts/skills.py check
python -X utf8 scripts/check_release.py
python -X utf8 scripts/skills.py test
```

Add a meaningful regression for a demonstrated defect. Check the actual record/status/history or resulting artifact rather than asserting that instructions contain preferred words. Preserve positive controls and distinguish new behavior from intentional compatibility changes. A zero-test success is not accepted by the suite runner.

Keep the runtime and project installer standard-library only. Agent-specific integration belongs in the skill instructions or an explicit supported adapter; do not add a model service, scheduler or another memory platform to solve an unrelated task.

For a release, update version and changelog, verify a clean setup and demo, inspect complete documentation and artifact contents, and run checks against the exact candidate. Installation tests must preserve receipts/local edits and test failure recovery. Respect the maintainer's publication and licensing decisions.

Contributions are accepted under this repository's [MIT license](LICENSE). Report sensitive issues through [SECURITY.md](SECURITY.md), not a public reproduction containing real data.
