# Security and private data

Context Keeper stores context in local SQLite files and generated Markdown. Those can contain sensitive project information. Keep stores, backups, source receipts and real briefs out of this repository and public issue attachments.

For an ordinary bug, provide a synthetic example through [issues](https://github.com/soin8293/context-keeper/issues). For a vulnerability or accidental data exposure, use **Security → Report a vulnerability** when available. If that option is unavailable, request a private reporting channel in an issue without including the vulnerability details or sensitive data. Do not post credentials, live database files or third-party messages publicly.

The maintainer reviews reports as capacity permits; there is no guaranteed response time. During the early-release phase, security fixes target the current release rather than a promised long-term support branch.

The runtime makes no network requests and has no model/provider credentials. SQLite read-only mode, source-root containment and install receipts provide specific safeguards; they do not certify arbitrary files, hostile schemas, concurrent clients or the security of an entire host. Use one designated writer and the owning project's governance.
