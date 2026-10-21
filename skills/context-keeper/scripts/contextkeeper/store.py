"""Context Keeper storage: durable records, non-destructive corrections, current view.

Design rules (from the AI context research):
- Original records are never destroyed. A correction supersedes; it does not delete.
- A record has a kind, an optional scope and a status in {current, superseded, retired}.
- Retrieval only returns the *current view* by default; history stays inspectable.
- Everything is deterministic and standard-library only. No model is required.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
from pathlib import Path
import uuid
from contextlib import closing

KINDS = ("constraint", "decision", "state", "fact", "question", "note")
STATUSES = ("current", "superseded", "retired")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS source (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ref TEXT NOT NULL,
  note TEXT,
  checked INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS record (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'current',
  supersedes INTEGER,
  superseded_by INTEGER,
  source_id INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS record_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id INTEGER NOT NULL,
  field TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT,
  reason TEXT,
  changed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  action TEXT NOT NULL,
  detail TEXT
);

CREATE INDEX IF NOT EXISTS record_status_idx ON record(status);
CREATE INDEX IF NOT EXISTS record_scope_idx ON record(scope);
CREATE INDEX IF NOT EXISTS record_kind_idx ON record(kind);

CREATE TABLE IF NOT EXISTS amendment (
  base_id INTEGER NOT NULL REFERENCES record(id),
  amendment_id INTEGER NOT NULL REFERENCES record(id),
  reason TEXT NOT NULL,
  PRIMARY KEY (base_id, amendment_id)
);
CREATE TABLE IF NOT EXISTS source_scan (
  origin TEXT NOT NULL, ref TEXT NOT NULL, scope TEXT NOT NULL,
  digest TEXT NOT NULL, unresolved INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (origin, ref, scope)
);
"""


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


class ContextError(Exception):
    pass


SCHEMA_VERSION = 2


def schema_info(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    columns = {t: {r[1] for r in conn.execute(f'PRAGMA table_info({t})')}
               for t in ('source', 'record')}
    return tables, columns


def preservation_manifest(conn):
    """Hash original data fields without exporting private record contents.

    New schema metadata (origin/mandatory) is intentionally separate. These
    hashes verify every original field, row and history entry across an upgrade.
    """
    fields = {
        'record': 'id,kind,scope,text,status,supersedes,superseded_by,source_id,created_at,updated_at',
        'record_history': 'id,record_id,field,old_value,new_value,reason,changed_at',
        'source': 'id,ref,note,created_at',
        'event': 'id,at,action,detail',
    }
    source_cols = {r[1] for r in conn.execute('PRAGMA table_info(source)')}
    if 'checked' in source_cols:
        fields['source'] += ',checked'
    manifest = {}
    for table, cols in fields.items():
        h = hashlib.sha256()
        count = 0
        for row in conn.execute(f'SELECT {cols} FROM {table} ORDER BY id'):
            h.update(json.dumps(list(row), ensure_ascii=True, separators=(',', ':')).encode())
            h.update(b'\n')
            count += 1
        manifest[table] = {'rows': count, 'columns': cols.split(','), 'sha256': h.hexdigest()}
    return manifest


def migration_preview(path):
    """Inspect only; never initialize or guess the root of an old reference."""
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.execute('BEGIN')  # one consistent read snapshot, no schema/data writes
        tables, columns = schema_info(conn)
        if not {'meta', 'source', 'record', 'record_history', 'event'} <= tables:
            raise ContextError('Not a recognized Context Keeper store; preserve it unchanged.')
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if version and version[0] not in ('1', str(SCHEMA_VERSION)):
            raise ContextError('Unsupported schema version; do not downgrade this store.')
        missing = [f'source.{c}' for c in ('checked', 'origin') if c not in columns['source']]
        missing += [f'record.{c}' for c in ('mandatory',) if c not in columns['record']]
        missing += [t for t in ('amendment', 'source_scan') if t not in tables]
        ambiguous = conn.execute('SELECT COUNT(*) FROM source WHERE origin IS NULL').fetchone()[0] if 'origin' in columns['source'] else conn.execute('SELECT COUNT(*) FROM source').fetchone()[0]
        return {'schema_required': SCHEMA_VERSION, 'changes': missing,
                'sources_requiring_explicit_origin': ambiguous,
                'automatic_origin_guessing': False,
                'preservation': preservation_manifest(conn)}


def migrate(path, origin=None, source_origins=None):
    """Explicit additive upgrade with an SQLite-consistent external backup."""
    report = migration_preview(path)
    path = Path(path).resolve()
    if source_origins is not None and not isinstance(source_origins, dict):
        raise ContextError('Origin map must be an object from source ID to root directory.')
    # Validate the complete explicit mapping before making any schema changes.
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as check:
        for sid, root in (source_origins or {}).items():
            if not isinstance(root, str) or not Path(root).is_dir() or not check.execute('SELECT 1 FROM source WHERE id=?', (int(sid),)).fetchone():
                raise ContextError(f'Invalid source origin mapping for #{sid}; database unchanged.')
    if origin is not None and not Path(origin).is_dir():
        raise ContextError('Explicit common source root must be an existing directory.')
    backup = path.with_name(path.name + '.backup-' + uuid.uuid4().hex)
    with closing(sqlite3.connect(path)) as conn, closing(sqlite3.connect(backup)) as dest:
        conn.backup(dest)
    conn = sqlite3.connect(path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        tables, cols = schema_info(conn)
        if 'checked' not in cols['source']:
            conn.execute('ALTER TABLE source ADD COLUMN checked INTEGER NOT NULL DEFAULT 1')
        if 'origin' not in cols['source']:
            conn.execute('ALTER TABLE source ADD COLUMN origin TEXT')
        if 'mandatory' not in cols['record']:
            conn.execute('ALTER TABLE record ADD COLUMN mandatory INTEGER NOT NULL DEFAULT 0')
        for statement in SCHEMA.split(';'):
            if statement.strip():
                conn.execute(statement)
        # Mapping is per source ID; a common root is only used when explicitly supplied.
        if origin is not None:
            conn.execute('UPDATE source SET origin=? WHERE origin IS NULL', (str(Path(origin).resolve()),))
        for sid, root in (source_origins or {}).items():
            changed = conn.execute('UPDATE source SET origin=? WHERE id=?', (str(Path(root).resolve()), int(sid))).rowcount
            if not changed:
                raise ContextError(f'No source #{sid}; migration rolled back. Backup: {backup}')
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        conn.commit()
    finally:
        conn.close()
    return {**report, 'backup': str(backup), 'applied': True}


class Store:
    def __init__(self, path: str, read_only: bool = False):
        self.path = str(path)
        self.read_only = read_only
        exists = Path(path).is_file()
        if read_only and not exists:
            raise ContextError('Store missing; explicitly install/init the intended project first.')
        self.conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) if read_only else sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if read_only:
            self.conn.execute('PRAGMA query_only=ON')
        if not exists:
            self.conn.executescript(SCHEMA)
            self.conn.execute('ALTER TABLE source ADD COLUMN origin TEXT')
            self.conn.execute('ALTER TABLE record ADD COLUMN mandatory INTEGER NOT NULL DEFAULT 0')
            self.conn.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            self.conn.commit()
        tables, cols = schema_info(self.conn)
        if not {'source_scan', 'amendment'} <= tables or not {'checked', 'origin'} <= cols['source'] or 'mandatory' not in cols['record']:
            self.close()
            raise ContextError('Legacy/incompatible schema. Run migrate (preview), then migrate --apply with explicit source origins; reads never migrate.')
        version = self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if not version or version[0] != str(SCHEMA_VERSION):
            self.close()
            raise ContextError('Unsupported schema version; inspect capabilities and migrate preview without changing the store.')

    def close(self) -> None:
        self.conn.close()

    # -- sources ---------------------------------------------------------
    def add_source(self, ref: str, note: str | None = None, checked: bool = True, origin: str | None = None) -> int:
        """`checked` marks a source the staleness check may verify against
        (text extracted from a file). A reference source is not checked."""
        cur = self.conn.execute(
            "INSERT INTO source (ref, note, checked, created_at, origin) VALUES (?,?,?,?,?)",
            (ref, note, 1 if checked else 0, now(), origin),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def find_or_add_source(self, ref: str, note: str | None = None, checked: bool = True, origin: str | None = None) -> int:
        """Reuse an existing source with the same ref and checked-state, else create it."""
        row = self.conn.execute(
            "SELECT id FROM source WHERE ref = ? AND checked = ? AND origin IS ?",
            (ref, 1 if checked else 0, origin),
        ).fetchone()
        if row is not None:
            return int(row["id"])
        return self.add_source(ref, note, checked, origin)

    # -- records ---------------------------------------------------------
    def add(
        self,
        kind: str,
        text: str,
        scope: str = "",
        source_id: int | None = None,
        mandatory: bool = False,
    ) -> int:
        if kind not in KINDS:
            raise ContextError(f"unknown kind '{kind}' (use one of {', '.join(KINDS)})")
        text = (text or "").strip()
        if not text:
            raise ContextError("record text must not be empty")
        ts = now()
        cur = self.conn.execute(
            "INSERT INTO record (kind, scope, text, status, source_id, created_at, updated_at, mandatory)"
            " VALUES (?,?,?, 'current', ?,?,?,?)",
            (kind, scope or "", text, source_id, ts, ts, int(mandatory)),
        )
        rid = int(cur.lastrowid)
        self._log(rid, "text", None, text, "created")
        self._event("add", f"{kind} #{rid}")
        self.conn.commit()
        return rid

    def get(self, rid: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM record WHERE id = ?", (rid,)).fetchone()
        if row is None:
            raise ContextError(f"no record #{rid}")
        return row

    def correct(self, rid: int, new_text: str, reason: str | None = None, scope: str | None = None) -> int:
        """Supersede an existing record with a new one. The old record is kept."""
        old = self.get(rid)
        if old["status"] != "current":
            raise ContextError(f"record #{rid} is '{old['status']}', not current")
        new_text = (new_text or "").strip()
        if not new_text:
            raise ContextError("correction text must not be empty")
        ts = now()
        cur = self.conn.execute(
            "INSERT INTO record (kind, scope, text, status, supersedes, source_id, created_at, updated_at)"
            " VALUES (?,?,?, 'current', ?, ?,?,?)",
            (
                old["kind"],
                scope if scope is not None else old["scope"],
                new_text,
                rid,
                old["source_id"],
                ts,
                ts,
            ),
        )
        new_id = int(cur.lastrowid)
        self.conn.execute('UPDATE record SET mandatory=? WHERE id=?', (old['mandatory'], new_id))
        # Partial amendments remain attached when either endpoint is corrected.
        for link in list(self.conn.execute('SELECT * FROM amendment WHERE base_id=? OR amendment_id=?', (rid, rid))):
            self.conn.execute('INSERT OR IGNORE INTO amendment VALUES (?,?,?)',
                              (new_id if link['base_id'] == rid else link['base_id'],
                               new_id if link['amendment_id'] == rid else link['amendment_id'], link['reason']))
        self.conn.execute(
            "UPDATE record SET status='superseded', superseded_by=?, updated_at=? WHERE id=?",
            (new_id, ts, rid),
        )
        self._log(rid, "status", "current", "superseded", reason or f"superseded by #{new_id}")
        self._log(new_id, "text", None, new_text, reason or f"corrects #{rid}")
        self._event("correct", f"#{rid} -> #{new_id}")
        self.conn.commit()
        return new_id

    def retire(self, rid: int, reason: str | None = None) -> None:
        row = self.get(rid)
        if row["status"] != "current":
            raise ContextError(f"record #{rid} is already '{row['status']}'")
        ts = now()
        self.conn.execute(
            "UPDATE record SET status='retired', updated_at=? WHERE id=?", (ts, rid)
        )
        self._log(rid, "status", "current", "retired", reason or "retired")
        self._event("retire", f"#{rid}")
        self.conn.commit()

    # -- queries ---------------------------------------------------------
    def current(self, scope: str | list[str] | None = None, kinds: tuple[str, ...] | None = None, include_globals: bool = True) -> list[sqlite3.Row]:
        sql = "SELECT * FROM record WHERE status='current'"
        params: list[object] = []
        if scope is not None:
            scopes = [scope] if isinstance(scope, str) else list(scope)
            if include_globals:
                scopes.append('')
            sql += ' AND (scope IN (' + ','.join('?' for _ in scopes) + ') OR mandatory=1)'
            params.extend(scopes)
        elif not include_globals:
            sql += " AND (scope != '' OR mandatory=1)"
        if kinds:
            sql += " AND kind IN (" + ",".join("?" * len(kinds)) + ")"
            params.extend(kinds)
        sql += " ORDER BY id"
        return list(self.conn.execute(sql, params))

    def superseded(self, scope: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM record WHERE status='superseded'"
        params: list[object] = []
        if scope is not None:
            scopes = [scope] if isinstance(scope, str) else list(scope)
            scopes.append('')
            sql += ' AND scope IN (' + ','.join('?' for _ in scopes) + ')'
            params.extend(scopes)
        sql += " ORDER BY id"
        return list(self.conn.execute(sql, params))

    def history(self, rid: int) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM record_history WHERE record_id=? ORDER BY id", (rid,)
            )
        )

    def events(self, limit: int = 50) -> list[sqlite3.Row]:
        return list(
            self.conn.execute("SELECT * FROM event ORDER BY id DESC LIMIT ?", (limit,))
        )

    def snapshot(self, scope=None, include_globals=True, required=()) -> dict[str, str]:
        """Map of current record id -> content hash. Used for freshness checks.

        The hash covers kind and text, so any edit that changes what a brief
        said — including a new scope or kind — registers as changed.
        """
        out: dict[str, str] = {}
        rows = {r['id']: r for r in self.current(scope, include_globals=include_globals)}
        for rid in required:
            rows[rid] = self.get(rid)
        rows = self.linked(rows)
        for row in sorted(rows.values(), key=lambda r: r['id']):
            src = self.conn.execute('SELECT ref,note,checked,origin FROM source WHERE id=?', (row['source_id'],)).fetchone()
            links = [tuple(r) for r in self.conn.execute('SELECT * FROM amendment WHERE base_id=? OR amendment_id=? ORDER BY base_id,amendment_id', (row['id'], row['id']))]
            payload = json.dumps([row['kind'], row['scope'], row['text'], row['status'], row['mandatory'], row['source_id'], list(src) if src else None, links]).encode('utf-8')
            out[str(row["id"])] = hashlib.sha1(payload).hexdigest()[:12]
        return out

    def amend(self, base_id, amendment_id, reason):
        if base_id == amendment_id or not reason.strip():
            raise ContextError('Amendment needs distinct records and an explicit clause/reason.')
        for rid in (base_id, amendment_id):
            if self.get(rid)['status'] != 'current':
                raise ContextError(f'Amendment endpoint #{rid} is not current.')
        self.conn.execute('INSERT INTO amendment VALUES (?,?,?)', (base_id, amendment_id, reason))
        self._event('amend', f'#{base_id} partly amended by #{amendment_id}: {reason}')
        self.conn.commit()

    def linked(self, rows):
        """Include both endpoints, including an unresolved retired endpoint for disclosure."""
        rows = dict(rows)
        while True:
            ids = set(rows)
            for link in self.amendments():
                if link['base_id'] in ids or link['amendment_id'] in ids:
                    for rid in (link['base_id'], link['amendment_id']):
                        rows[rid] = self.get(rid)
            if set(rows) == ids:
                return rows

    def amendments(self):
        """Resolve correction chains without deleting the historical relationship."""
        def latest(rid):
            seen = set()
            row = self.get(rid)
            while row['status'] == 'superseded' and row['superseded_by']:
                if row['id'] in seen:
                    raise ContextError('Correction chain cycle; reconcile the retained store.')
                seen.add(row['id'])
                row = self.get(row['superseded_by'])
            return row['id']
        result = {}
        for link in self.conn.execute('SELECT * FROM amendment ORDER BY base_id,amendment_id'):
            a, b = latest(link['base_id']), latest(link['amendment_id'])
            result[(a, b, link['reason'])] = {'base_id': a, 'amendment_id': b, 'reason': link['reason']}
        return list(result.values())

    # -- events ----------------------------------------------------------
    def log_event(self, action: str, detail: str) -> None:
        """Public action-log write, for commands that are not record edits."""
        self._event(action, detail)
        self.conn.commit()

    # -- internal --------------------------------------------------------
    def _log(self, rid: int, field: str, old: str | None, new: str | None, reason: str | None) -> None:
        self.conn.execute(
            "INSERT INTO record_history (record_id, field, old_value, new_value, reason, changed_at)"
            " VALUES (?,?,?,?,?,?)",
            (rid, field, old, new, reason, now()),
        )

    def _event(self, action: str, detail: str) -> None:
        self.conn.execute(
            "INSERT INTO event (at, action, detail) VALUES (?,?,?)", (now(), action, detail)
        )
