# Context Keeper maintenance

The implementation and reusable skill live in `skills/context-keeper/`. Use Python 3.11+ and keep the runtime standard-library only. No network/model/embedding service is needed for runtime behavior.

Preserve original records and history; corrections supersede and amendments link rather than delete. Whole records and required groups must not be silently clipped. Reads and dry runs must not migrate or write to SQLite. Preserve checked source identity and expose unknown provenance rather than guessing.

Use only synthetic fixtures in tests, examples and issues. Never add project databases, private conversations, receipts, machine paths or credentials to source or release artifacts. Respect the owning project's write route and one-writer boundary.

Before claiming a change works, run the documented structure/release checks and tests from README.md and exercise an actual affected workflow. Documentation must be nonempty, linked and usable from a clean clone. Keep version, changelog, examples and known limits consistent. Existing local changes and install receipts are not disposable.

Use one repository-level AI-assistance disclosure. Preserve contributor and license attribution; do not add per-file/tool signatures or AI co-author trailers. Public release and private operational data have separate scopes.
