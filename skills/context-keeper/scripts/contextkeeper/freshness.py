"""Compact scoped record/source fingerprints and explicit source diagnostics."""
import hashlib
import json
import re
from pathlib import Path

from .ingest import discover_files, ingest, source_config


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def origins(store, scope=None, include_globals=True, required=()):
    scopes = None if scope is None else set([scope] if isinstance(scope, str) else scope)
    if scopes is not None and include_globals:
        scopes.add('')
    result = {(r['origin'], r['scope']) for r in store.conn.execute('SELECT DISTINCT origin,scope FROM source_scan')
              if (scopes is None and (include_globals or r['scope'])) or (scopes is not None and r['scope'] in scopes)}
    rows = {r['id']: r for r in store.current(scope, include_globals=include_globals)}
    for rid in required:
        rows[rid] = store.get(rid)
    for r in store.linked(rows).values():
        src = store.conn.execute('SELECT * FROM source WHERE id=?', (r['source_id'],)).fetchone()
        if src and src['checked'] and src['origin']:
            result.add((src['origin'], r['scope']))
    return sorted(result)


def source_fingerprint(store, scope=None, include_globals=True, required=()):
    states = []
    for origin, source_scope in origins(store, scope, include_globals, required):
        root = Path(origin)
        config = source_config(root)
        files, skipped = discover_files(root, config.get('max_file_bytes', 1024 * 1024), config=config)
        state = []
        for rel, path in files:
            try:
                raw = path.read_bytes()
                if b'<!-- context-keeper:snapshot' in raw or b'<!-- context-keeper:brief' in raw:
                    continue
                state.append((rel, hashlib.sha256(raw).hexdigest()))
            except OSError:
                state.append((rel, 'unreadable'))
        states.append([origin, source_scope, config, state, skipped])
    return digest(states)


def source_issues(store, scope=None, include_globals=True, required=()):
    issues = []
    for origin, source_scope in origins(store, scope, include_globals, required):
        if not Path(origin).is_dir():
            issues.append({'origin': origin, 'scope': source_scope, 'reason': 'source_root_missing'})
            continue
        report = ingest(store, Path(origin), scope=source_scope, dry_run=True)
        for key in ('stale', 'duplicates', 'unresolved', 'unknown_origins', 'source_changes'):
            issues.extend({'origin': origin, 'scope': source_scope, 'category': key, **item} for item in report[key])
        issues.extend({'origin': origin, 'scope': source_scope, **item} for item in report['skipped']
                      if item['reason'] not in ('configured_exclusion', 'generated_brief'))
        if report['totals']['added']:
            issues.append({'origin': origin, 'scope': source_scope, 'reason': 'unrecorded_candidates', 'count': report['totals']['added']})
    rows = {r['id']: r for r in store.current(scope, include_globals=include_globals)}
    for rid in required:
        rows[rid] = store.get(rid)
    for r in store.linked(rows).values():
        src = store.conn.execute('SELECT * FROM source WHERE id=?', (r['source_id'],)).fetchone()
        if src and src['checked'] and not src['origin']:
            issues.append({'id': r['id'], 'source_id': src['id'], 'reason': 'unknown_source_origin'})
        if re.search(r'\b(?:SUPERSEDED|OVERRIDDEN|REPLACED BY)\b', r['text']) and not any(r['id'] in (link['base_id'],link['amendment_id']) for link in store.amendments()):
            issues.append({'id': r['id'], 'reason': 'explicit_change_marker_requires_writer_review', 'automatic_status_change': False})
    return issues


def compact_snapshot(store, scope=None, include_globals=True, required=()):
    return {'version': 2, 'scope': scope, 'include_globals': include_globals, 'required': list(required),
            'records': digest(store.snapshot(scope, include_globals, required)),
            'sources': source_fingerprint(store, scope, include_globals, required)}
