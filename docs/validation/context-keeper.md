# Context Keeper validation

Runtime v0.4.1/schema v2 is covered by 110 synthetic Context Keeper tests and the standalone repository's installer/release checks. The [testing guide](../testing.md) describes operations, evidence and limits; the [demo](../../examples/demo.py) creates actual source-linked artifacts through the native project workflow.

The tested contracts are retained history, visible whole-record omissions, deterministic extraction and limits, explicit provenance/scope, read-only queries, source drift, linked amendments, compact freshness, complete-output budgets and controlled legacy upgrades. No private case data or operational database is included.

Before publication, verify a clean clone, exact-head Linux/Windows CI, complete documentation, the archive and checksums, license/attribution and the selected public surface. Installing the skill alone does not migrate a project's retained runtime. Source/history reconciliation remains an authorized writer decision.
