"""Command-line interface for Context Keeper."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import sqlite3

from .brief import build_brief, diff_snapshot, extract_snapshot
from .ingest import MAX_FILE_BYTES, ingest, acknowledge_source
from .store import KINDS, ContextError, Store, SCHEMA_VERSION, migrate, migration_preview
from .freshness import compact_snapshot, source_issues

DEFAULT_DB = ".context-keeper/context.sqlite"


def _store(args) -> Store:
    writer = args.cmd in ('add', 'correct', 'retire', 'amend') or (args.cmd == 'ingest' and not args.dry_run) or (args.cmd == 'reconcile' and args.acknowledge_source)
    args._opened_store = Store(args.db, read_only=not writer)
    return args._opened_store


def cmd_init(args) -> int:
    Store(args.db).close()
    print(f"initialized {args.db}")
    return 0


def cmd_add(args) -> int:
    s = _store(args)
    src = None
    note = ""
    if args.source:
        # Manual sources are references by default: they are not treated as the
        # file a record was extracted from, so the staleness check ignores them.
        src = s.find_or_add_source(args.source, note="manual", checked=args.source_checked,
                                   origin=str(pathlib.Path(args.source_root).resolve()) if args.source_root else None)
        note = " (source checked for staleness)" if args.source_checked else " (source is a reference)"
    rid = s.add(args.kind, args.text, scope=args.scope or "", source_id=src, mandatory=args.mandatory)
    print(f"added {args.kind} #{rid}{note}")
    s.close()
    return 0


def cmd_correct(args) -> int:
    s = _store(args)
    rid = s.correct(args.id, args.text, reason=args.reason, scope=args.scope)
    print(f"corrected #{args.id} -> #{rid} (old kept, marked superseded)")
    s.close()
    return 0


def cmd_retire(args) -> int:
    s = _store(args)
    s.retire(args.id, reason=args.reason)
    print(f"retired #{args.id}")
    s.close()
    return 0


def cmd_search(args) -> int:
    s = _store(args)
    rows = s.current(scope=args.scope)
    if args.kinds:
        rows = [r for r in rows if r["kind"] in args.kinds]
    terms = [t.lower() for t in args.query.split()]
    out = []
    for r in rows:
        low = r["text"].lower()
        hits = [t in low for t in terms]
        ok = all(hits) if args.match == "all" else any(hits)
        if ok:
            out.append(r)
    for r in out:
        print(f"[{r['kind'][0].upper()}{r['id']}] ({r['scope'] or 'global'}) {r['text']}")
    if not out:
        print("(no current records matched)")
    s.close()
    return 0


def cmd_brief(args) -> int:
    s = _store(args)
    result = build_brief(
        s,
        args.task,
        scope=args.scope,
        budget_chars=args.budget,
        include_superseded=args.include_superseded,
        reserved_share=args.reserved_share,
        full_omitted=args.full_omitted,
        output_chars=args.output_budget,
        required=args.require,
        global_policy=args.globals,
    )
    if args.output:
        path = pathlib.Path(args.output)
        if path.exists():
            print(f"refusing to overwrite existing brief: {path}", file=sys.stderr)
            s.close()
            return 2
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result["text"], encoding="utf-8")
        print(f"wrote brief to {path}")
        print(json.dumps(result["coverage"], indent=2))
    else:
        print(result["text"])
    s.close()
    return 1 if result['incomplete'] else 0


def cmd_check(args) -> int:
    try:
        text = pathlib.Path(args.brief).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(f"cannot read brief {args.brief}: {exc}", file=sys.stderr)
        return 2
    old = extract_snapshot(text)
    if old is None:
        print("no snapshot found in that file (is it a Context Keeper brief?)", file=sys.stderr)
        return 2
    s = _store(args)
    if old.get('version') == 2:
        new = compact_snapshot(s, old['scope'], old['include_globals'], old['required'])
        diff = diff_snapshot(old, new)
        issues = source_issues(s, old['scope'], old['include_globals'], old['required'])
        incomplete = '**Status:** INCOMPLETE' in text
        fresh = diff['fresh'] and not issues and not incomplete
        print('FRESH: scoped records and declared source bytes/configuration unchanged; no unresolved source issues.' if fresh else 'STALE: scoped records/sources changed or the saved packet is incomplete; run reconcile --json and rebuild.')
        if not old['sources'] or not s.conn.execute('SELECT 1 FROM source_scan LIMIT 1').fetchone():
            print('Record/reference-only packet: no scanned source inventory; semantic authority is not verified.')
        s.close()
        return 0 if fresh else 1
    diff = diff_snapshot(old, s.snapshot())
    root = pathlib.Path(args.project_root).resolve() if args.project_root else None
    db_dir = pathlib.Path(args.db).resolve().parent
    if root is None and db_dir.name == '.context-keeper':
        root = db_dir.parent
    source_report = ingest(s, root, dry_run=True) if root is not None else None
    source_changed = bool(source_report and (source_report['stale'] or source_report['skipped'] or source_report['duplicates'] or source_report['totals']['added'] or source_report['source_changes'] or source_report['unresolved'] or source_report['unknown_origins']))
    print('Legacy snapshot: full-store comparison; regenerate once for scoped v2 fingerprints.')
    if diff["fresh"] and not source_changed:
        print("FRESH: nothing has changed since that brief.")
        if root is None:
            print('Record-only check: source files not checked; supply --project-root.')
    else:
        print("STALE: the current context has changed since that brief.")
        for rid in diff["added"]:
            print(f"  + new current record #{rid}")
        for rid in diff["changed"]:
            print(f"  ~ changed record #{rid}")
        for rid in diff["removed_from_current"]:
            print(f"  - no longer current: #{rid}")
        if source_changed:
            print('  Source documents changed or have unresolved skips/duplicates; ingest and reconcile before reusing.')
    s.close()
    return 0 if diff['fresh'] and not source_changed else 1


def cmd_ingest(args) -> int:
    s = _store(args)
    report = ingest(
        s,
        pathlib.Path(args.path),
        scope=args.scope or "",
        dry_run=args.dry_run,
        max_file_bytes=args.max_file_bytes,
        max_items=args.max_items,
        max_files=args.max_files,
    )
    verb = "would add" if args.dry_run else "added"
    print(f"scanned {len(report['files'])} file(s) under {report['root']}")
    for f in report["files"]:
        if f["items"]:
            print(
                f"  {f['file']}: {verb} {f['added']}, already known {f['existing']}, "
                f"near-duplicate {f['duplicates']}"
            )
    for kind, n in sorted(report["added_kinds"].items()):
        print(f"  + {kind}: {n}")
    t = report["totals"]
    print(f"{verb} {t['added']} record(s); {t['existing']} already known; {t['duplicates']} near-duplicate")
    if report["skipped"]:
        print(f"\nskipped ({len(report['skipped'])}) — not scanned:")
        for sk in report["skipped"]:
            extra = f" ({sk['size']} bytes)" if sk.get("size") else ""
            print(f"  {sk['file']}{extra} — {sk['reason']}")
    if report["duplicates"]:
        print(f"\nnear-duplicates ({len(report['duplicates'])}) — not added, decide:")
        for d in report["duplicates"]:
            where = "a record added earlier in this run" if d["of_id"] < 0 else f"#{d['of_id']}"
            print(f"  [{d['kind']}] {d['text'][:72]}")
            print(f"      ~ {where} (similarity {d['similarity']}): {d['of_text'][:64]}")
            print("      fix with: correct <id> \"<merged text>\"  |  retire the other")
    if report["stale"]:
        print(f"\npossibly stale ({len(report['stale'])}) — source changed, decide:")
        for rec in report["stale"]:
            print(f"  [#{rec['id']} {rec['kind']}] {rec['text'][:70]}")
            print(f"      source: {rec['ref']}")
        print("  fix with: correct <id> \"<new text>\"  |  retire <id>")
    for key in ('source_changes', 'unresolved', 'unknown_origins'):
        if report[key]:
            print(f'{key}: ' + json.dumps(report[key], ensure_ascii=True))
    if report['unresolved']:
        print('Inspect the exact source revision, reconcile records, then use reconcile --acknowledge-source FILE --project-root ROOT --reason TEXT if the uncaptured change is understood.')
    s.close()
    return 0


def cmd_status(args) -> int:
    s = _store(args)
    cur = s.current(scope=args.scope)
    from collections import Counter

    counts = Counter(r["kind"] for r in cur)
    print(f"database: {args.db}")
    print(f"current records: {len(cur)}")
    for k in KINDS:
        if counts.get(k):
            print(f"  {k}: {counts[k]}")
    sup = s.superseded(scope=args.scope)
    print(f"superseded (kept for history): {len(sup)}")
    s.close()
    return 0


def cmd_log(args) -> int:
    s = _store(args)
    for e in s.events(args.limit):
        print(f"{e['at']}  {e['action']:<8} {e['detail'] or ''}")
    s.close()
    return 0


def cmd_capabilities(args):
    print(json.dumps({'runtime': 'context-keeper', 'schema': SCHEMA_VERSION,
                      'read_only': ['status', 'search', 'show', 'brief', 'check', 'log', 'reconcile', 'ingest --dry-run', 'migrate preview'],
                      'features': ['explicit-source-origins', 'governing-prose', 'multi-scope', 'amendments', 'whole-output-budget', 'scoped-fingerprints'],
                      'automatic_migration': False}, indent=2))
    return 0


def cmd_show(args):
    s = _store(args)
    row = s.get(args.id)
    source = s.conn.execute('SELECT * FROM source WHERE id=?', (row['source_id'],)).fetchone()
    print(json.dumps({'record': dict(row), 'source': dict(source) if source else None,
                      'history': [dict(r) for r in s.history(args.id)],
                      'amendments': [link for link in s.amendments() if args.id in (link['base_id'],link['amendment_id'])]}, indent=2, ensure_ascii=False))
    s.close()
    return 0


def cmd_migrate(args):
    mapping = json.loads(pathlib.Path(args.origin_map).read_text(encoding='utf-8')) if args.origin_map else None
    report = migrate(args.db, args.source_root, mapping) if args.apply else migration_preview(args.db)
    print(json.dumps(report, indent=2))
    return 0


def cmd_amend(args):
    s = _store(args)
    try:
        s.amend(args.base_id, args.amendment_id, args.reason)
        print(f'Linked #{args.base_id} -> #{args.amendment_id}; both records kept current. Read back both clauses.')
    finally:
        s.close()
    return 0


def cmd_reconcile(args):
    s = _store(args)
    try:
        if args.acknowledge_source:
            if not args.project_root or not args.reason or len(args.scope or []) > 1:
                raise ContextError('Acknowledgment requires --project-root, --reason and at most one --scope.')
            acknowledge_source(s, args.project_root, args.acknowledge_source, (args.scope or [''])[0], args.reason)
        issues = source_issues(s, args.scope)
        # Words are review leads, never an automatic status/authority decision.
        leads = [{'id': r['id'], 'text': r['text'], 'reason': 'explicit_change_word_without_structured_link'}
                 for r in s.current(args.scope) if any(w in r['text'].lower() for w in ('superseded', 'overridden', 'replaced by'))
                 and not s.conn.execute('SELECT 1 FROM amendment WHERE base_id=? OR amendment_id=?', (r['id'], r['id'])).fetchone()]
        result = {'issues': issues, 'review_leads': leads,
                  'actions': ['inspect governing sources', 'correct/retire verified obsolete records', 'amend BASE NEW --reason CLAUSE for partial overrides', 'explicitly map unknown origins through migrate', 'review skipped/uncaptured source revisions before acknowledging'],
                  'automatic_truth_or_status_changes': False}
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 1 if issues or leads else 0
    finally:
        s.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="contextkeeper", description="Context Keeper: keep and hand over project context.")
    p.add_argument("--db", default=DEFAULT_DB, help=f"path to the context database (default: {DEFAULT_DB})")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create the context database").set_defaults(func=cmd_init)
    sub.add_parser('capabilities', help='show supported runtime operations without opening a store').set_defaults(func=cmd_capabilities)
    mg = sub.add_parser('migrate', help='preview an explicit backed-up schema/origin migration')
    mg.add_argument('--apply', action='store_true')
    mg.add_argument('--source-root', help='Explicit common origin for all unmapped legacy sources; never guessed')
    mg.add_argument('--origin-map', help='JSON object mapping exact source IDs to their actual origin roots')
    mg.set_defaults(func=cmd_migrate)

    a = sub.add_parser("add", help="add a record")
    a.add_argument("kind", choices=KINDS)
    a.add_argument("text")
    a.add_argument("--scope", default="")
    a.add_argument("--source", default=None, help="a reference (not checked for staleness)")
    a.add_argument('--source-root', help='Explicit extraction root for a checked file source')
    a.add_argument('--mandatory', action='store_true', help='Explicit policy applicable across scopes, even when globals are excluded')
    a.add_argument(
        "--source-checked",
        action="store_true",
        help="treat --source as the file this text was extracted from (checked for staleness)",
    )
    a.set_defaults(func=cmd_add)

    c = sub.add_parser("correct", help="supersede a record (old one is kept)")
    c.add_argument("id", type=int)
    c.add_argument("text")
    c.add_argument("--reason", default=None)
    c.add_argument("--scope", default=None)
    c.set_defaults(func=cmd_correct)

    r = sub.add_parser("retire", help="mark a record retired (kept, not current)")
    r.add_argument("id", type=int)
    r.add_argument("--reason", default=None)
    r.set_defaults(func=cmd_retire)

    se = sub.add_parser("search", help="search current records")
    se.add_argument("query")
    se.add_argument("--scope", action='append', default=None)
    se.add_argument("--kind", dest="kinds", action="append", choices=KINDS)
    se.add_argument("--match", choices=("all", "any"), default="all")
    se.set_defaults(func=cmd_search)
    sh = sub.add_parser('show', help='Read one exact record, status/history, source and amendment links')
    sh.add_argument('id', type=int)
    sh.set_defaults(func=cmd_show)

    b = sub.add_parser("brief", help="assemble a bounded, source-linked brief for a task")
    b.add_argument("task")
    b.add_argument("--scope", action='append', default=None)
    b.add_argument('--globals', choices=('all', 'relevant', 'exclude'), default='all')
    b.add_argument('--require', type=int, action='append', default=[], help='Required record ID, repeatable; linked amendments travel together')
    b.add_argument('--output-budget', type=int, default=16000, help='Complete Markdown cap including metadata/citations; never truncates records')
    b.add_argument("--budget", type=int, default=8000, help="character budget (default 8000)")
    b.add_argument("--output", default=None)
    b.add_argument("--include-superseded", action="store_true")
    b.add_argument(
        "--reserved-share",
        type=float,
        default=0.5,
        help="share of the budget constraints/decisions may occupy (default 0.5)",
    )
    b.add_argument(
        "--full-omitted",
        action="store_true",
        help="list every omitted record id instead of summarising by kind",
    )
    b.set_defaults(func=cmd_brief)

    ch = sub.add_parser("check", help="check if a saved brief is still fresh")
    ch.add_argument("brief")
    ch.add_argument('--project-root', help='Check current source documents under this project')
    ch.set_defaults(func=cmd_check)

    ing = sub.add_parser("ingest", help="scan the project's docs into records (no typing)")
    ing.add_argument("path", nargs="?", default=".", help="project directory (default: .)")
    ing.add_argument("--scope", default=None, help="scope to tag ingested records with")
    ing.add_argument("--dry-run", action="store_true", help="report what would be added, write nothing")
    ing.add_argument(
        "--max-file-bytes",
        type=int,
        default=None,
        help=f"skip files larger than this, but report them (default {MAX_FILE_BYTES})",
    )
    ing.set_defaults(func=cmd_ingest)
    ing.add_argument('--max-items', type=int)
    ing.add_argument('--max-files', type=int)

    st = sub.add_parser("status", help="summarize the current view")
    st.add_argument("--scope", action='append', default=None)
    st.set_defaults(func=cmd_status)

    lg = sub.add_parser("log", help="show the action log")
    lg.add_argument("--limit", type=int, default=50)
    lg.set_defaults(func=cmd_log)
    am = sub.add_parser('amend', help='Link an explicit partial override, preserving both records')
    am.add_argument('base_id', type=int)
    am.add_argument('amendment_id', type=int)
    am.add_argument('--reason', required=True, help='Name the affected clause and verified relationship')
    am.set_defaults(func=cmd_amend)
    rc = sub.add_parser('reconcile', help='Read-only source/record maintenance report; acknowledgment is an explicit write')
    rc.add_argument('--scope', action='append')
    rc.add_argument('--json', action='store_true', help='Structured report (also the default)')
    rc.add_argument('--project-root')
    rc.add_argument('--acknowledge-source')
    rc.add_argument('--reason')
    rc.set_defaults(func=cmd_reconcile)

    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    args = build_parser().parse_args(argv)
    if args.cmd not in ('init', 'capabilities') and not pathlib.Path(args.db).is_file():
        print('Context store missing; explicitly install/init the intended project first.', file=sys.stderr)
        return 2
    try:
        return args.func(args)
    except (ContextError, OSError, UnicodeError, sqlite3.Error, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        if getattr(args, '_opened_store', None) is not None:
            args._opened_store.close()


if __name__ == "__main__":
    raise SystemExit(main())
