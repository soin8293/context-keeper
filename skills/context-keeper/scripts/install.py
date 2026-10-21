"""Preview or explicitly wire one project with the bundled Context Keeper runtime."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid
import sqlite3

HERE = Path(__file__).resolve().parent
BEGIN = '<!-- context-keeper:begin -->'
END = '<!-- context-keeper:end -->'
BLOCK = f'''{BEGIN}
## Project context

Use the project-owned `.context-keeper/ck.py` runner; inspect `capabilities` on a
retained installation. Queries and dry runs in schema v2 are read-only. Build a
task brief with explicit scopes, read its status and omissions, and check before
reuse. Route ingestion/reconciliation through the authorized writer. Correct,
retire or explicitly link partial amendments without deleting history.
The adjacent context.agent.json defines this tool's supported write route.
{END}
'''
RUNNER = '''from pathlib import Path
import os, sys
local = Path(__file__).resolve().parent
if (local / '.maintenance').exists():
    print('Context Keeper maintenance in progress; retry after the owner completes the upgrade.', file=sys.stderr)
    raise SystemExit(75)
sys.path.insert(0, str(local))
os.chdir(local.parent)
from contextkeeper.cli import main
raise SystemExit(main())
'''
SHARED_RUNNER = RUNNER.replace('os.chdir(local.parent)', '''if not any(arg == '--db' or arg.startswith('--db=') for arg in sys.argv[1:]):
    sys.argv[1:1] = ['--db', str(local / 'context.sqlite')]''')
ROUTER = '''# Project context

Inspect `python .context-keeper/ck.py capabilities` before assuming runtime support.
Use `brief "task" --scope SCOPE --output .context-keeper/briefs/task-v1.md`, then read it.
Repeat --scope for a cross-scope task; --require ID includes required context and its amendments.
Use `check PATH` before reusing a brief; incomplete packets need reconciliation.
Native queries, reconcile reports and ingest --dry-run are read-only in schema v2.
The authorized writer uses ingest after governing docs change, reviews reconcile
--json and handles verified changes with add/correct/retire/amend. Never infer
approval or retire records from a word/date. Source selection is project-owned
in .context-keeper/sources.json. Disclose omissions, skips and unresolved sources.
Runtime updates use the originating reusable skill installer, never replace the database.
'''


def file_hashes(folder):
    if any(p.is_symlink() for p in Path(folder).rglob('*')):
        raise ValueError('Runtime contains linked files; reconcile before installation')
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(folder).rglob('*.py') if '__pycache__' not in p.parts}


def inspect_legacy(path, output=None):
    """Prepare a file-integrity receipt for human review, without opening SQLite."""
    store=Path(path).resolve()/'.context-keeper'
    package=store/'contextkeeper'
    if store.is_symlink() or package.is_symlink() or not package.is_dir():
        raise ValueError('Resolve an existing real project runtime before inspection')
    runner,router=store/'ck.py',store/'CONTEXT.md'
    if any(p.is_symlink() or not p.is_file() for p in (runner,router)):
        raise ValueError('Legacy runner/router must be real files')
    payload={'files':file_hashes(package),'runner_sha256':hashlib.sha256(runner.read_bytes()).hexdigest(),
             'router_sha256':hashlib.sha256(router.read_bytes()).hexdigest(),
             'review_required':True,'database_opened':False}
    if not payload['files']:
        raise ValueError('Runtime has no Python files')
    text=json.dumps(payload,indent=2)+'\n'
    if output:
        output=Path(output).resolve()
        if output.is_relative_to(store) or output.exists():
            raise ValueError('Choose a new external receipt path outside the context directory')
        output.write_text(text,encoding='utf-8')
        print(json.dumps({'receipt':str(output),'review_required':True,'database_opened':False}))
    else:
        print(text,end='')
    return 0


def wire_project(path: Path, do_ingest=True, wire_agents=True, apply=True, adopt_receipt=None, shared_runner=None):
    path = Path(path).resolve()
    if not path.is_dir():
        raise ValueError('Project directory does not exist')
    store = path / '.context-keeper'
    if store.is_symlink() or (store.exists() and store.resolve().parent != path):
        raise ValueError('Context directory must be a real project child')
    agents = path / 'AGENTS.md'
    text = agents.read_text(encoding='utf-8') if agents.exists() else ''
    if wire_agents and (agents.is_symlink() or ((BEGIN in text) != (END in text)) or text.count(BEGIN) > 1 or text.count(END) > 1 or
                        (BEGIN in text and text.index(BEGIN) > text.index(END))):
        raise ValueError('Malformed Context Keeper instruction markers; reconcile manually')
    previous = store / '.runtime-install.json'
    receipt_path = Path(adopt_receipt).resolve() if adopt_receipt else previous
    if adopt_receipt and previous.exists():
        raise ValueError('A recognized installation already has a receipt; do not override its local-edit guard')
    if adopt_receipt and (not receipt_path.is_file() or receipt_path.is_relative_to(store)):
        raise ValueError('Adoption requires a verified external receipt, outside the project context directory')
    package = store / 'contextkeeper'
    router = store / 'CONTEXT.md'
    if package.is_symlink():
        raise ValueError('Project runtime must not be a symlink')
    if ((store / 'context.sqlite').exists() or router.exists()) and not receipt_path.is_file():
        raise ValueError('Existing project context has no receipt; preserve and reconcile it before adopting')
    src_hashes = file_hashes(HERE / 'contextkeeper')
    current_hashes = {}
    old = {}
    if package.exists() or (store / 'ck.py').exists():
        if not receipt_path.is_file():
            raise ValueError('Existing runtime has no receipt; preserve and reconcile it before adopting')
        old = json.loads(receipt_path.read_text(encoding='utf-8'))
        current_hashes = file_hashes(package)
        runner = store / 'ck.py'
        if current_hashes != old['files'] or not runner.exists() or hashlib.sha256(runner.read_bytes()).hexdigest() != old['runner_sha256']:
            raise ValueError('Project runtime has local edits; reconcile before updating')
        if not router.exists() or hashlib.sha256(router.read_bytes()).hexdigest() != old.get('router_sha256'):
            raise ValueError('Project context router has local edits; reconcile before updating')
    if shared_runner is None:
        shared_runner = old.get('runner_mode') == 'shared'
    if not apply:
        print(json.dumps({'project': str(path), 'would_install_runtime': True,
                          'would_ingest': do_ingest, 'would_wire_agents': wire_agents,
                          'would_adopt_verified_receipt': bool(adopt_receipt),
                          'runner_mode': 'shared' if shared_runner else 'project',
                          'existing_database': (store / 'context.sqlite').exists()}))
        return 0
    # Updating code must not accidentally migrate an existing project database.
    db = store / 'context.sqlite'
    if db.exists():
        from contextkeeper.store import Store, ContextError
        try:
            Store(str(db), read_only=True).close()
        except (ContextError, sqlite3.Error) as exc:
            raise ValueError(f'Existing database requires separate migration/reconciliation before runtime installation: {exc}') from exc
    store.mkdir(exist_ok=True)
    token = uuid.uuid4().hex
    stage = store / ('.runtime-stage-' + token)
    if not stage.resolve().is_relative_to(store.resolve()):
        raise ValueError('Invalid staging location')
    shutil.copytree(HERE / 'contextkeeper', stage, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    if file_hashes(stage) != src_hashes:
        raise ValueError('Staged runtime integrity check failed')
    backup = None
    if package.exists():
        backups = store / 'backups'
        backups.mkdir(exist_ok=True)
        backup = backups / token
        if not backup.resolve().is_relative_to(store.resolve()):
            raise ValueError('Invalid backup location')
        backup.mkdir()
        package.rename(backup / 'contextkeeper')
        shutil.copy2(store / 'ck.py', backup / 'ck.py')
        shutil.copy2(receipt_path, backup / '.runtime-install.json')
        shutil.copy2(router, backup / 'CONTEXT.md')
    try:
        stage.rename(package)
    except OSError:
        if backup is not None and not package.exists():
            (backup / 'contextkeeper').rename(package)
        raise
    (store / 'ck.py').write_text(SHARED_RUNNER if shared_runner else RUNNER, encoding='utf-8', newline='\n')
    (store / 'CONTEXT.md').write_text(ROUTER, encoding='utf-8')
    ignore = store / '.gitignore'
    if not ignore.exists():
        ignore.write_text('context.sqlite*\ncontext.agent.json\nbriefs/\nbackups/\ndb_backups/\ndb_writes.log\n.runtime-install.json\n.runtime-stage-*/\n.maintenance\n__pycache__/\n', encoding='utf-8')
    notes = store / 'context.agent.json'
    if not notes.exists():
        notes.write_text(json.dumps({'about': 'Private project context, not a canonical source database',
            'writes': 'Use the project-owned .context-keeper/ck.py add, correct, retire, amend and ingest commands; reconcile acknowledgments and migrate --apply are explicit writes; no direct SQL edits.',
            'write_route': 'Use this project .context-keeper/ck.py supported writer commands. Preserve record history; preview schema/origin migrations with backups; no direct record edits.',
            'privacy': 'Keep database and generated briefs private to the owning project.'}, indent=2)+'\n', encoding='utf-8')
    if wire_agents:
        if BEGIN in text:
            if text.index(BEGIN) > text.index(END):
                raise ValueError('Reversed Context Keeper markers')
            text = text[:text.index(BEGIN)] + BLOCK.rstrip() + text[text.index(END)+len(END):]
        else:
            text = text.rstrip() + ('\n\n' if text.strip() else '') + BLOCK
        if agents.exists():
            backup = store / 'backups' / ('AGENTS-' + token + '.md')
            backup.parent.mkdir(exist_ok=True)
            shutil.copy2(agents, backup)
        agents.write_text(text, encoding='utf-8')
    from contextkeeper.store import Store
    from contextkeeper.ingest import ingest
    s = Store(str(store / 'context.sqlite'), read_only=db.exists() and not do_ingest)
    try:
        report = ingest(s, path) if do_ingest else None
    finally:
        s.close()
    payload = {'files': src_hashes, 'runner_sha256': hashlib.sha256((store/'ck.py').read_bytes()).hexdigest(),
               'router_sha256': hashlib.sha256(router.read_bytes()).hexdigest(),
               'runner_mode': 'shared' if shared_runner else 'project',
               'installed_utc': datetime.now(timezone.utc).isoformat()}
    previous.write_text(json.dumps(payload, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'project': str(path), 'runtime': 'installed',
                      'ingest': report['totals'] if report is not None else 'skipped',
                      'review_skips_duplicates_stale': bool(report and (report['skipped'] or report['duplicates'] or report['stale']))}))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    inspect=sub.add_parser('inspect-legacy',help='Hash a retained runtime/router for review without opening or changing its database')
    inspect.add_argument('path',type=Path)
    inspect.add_argument('--output',type=Path,help='New external review receipt; inspect source before using it for adoption')
    q = sub.add_parser('project')
    q.add_argument('path', type=Path)
    q.add_argument('--apply', action='store_true')
    q.add_argument('--wire-agents', action='store_true')
    q.add_argument('--no-ingest', action='store_true')
    q.add_argument('--adopt-receipt', help='Verified external runtime/router/runner hashes for a reviewed unreceipted legacy installation')
    q.add_argument('--shared-runner', action='store_true', default=None, help='Keep caller cwd/source/output paths, with the shared database pinned beside the runner')
    a = p.parse_args(argv)
    try:
        if a.command=='inspect-legacy':
            return inspect_legacy(a.path,a.output)
        return wire_project(a.path, do_ingest=not a.no_ingest, wire_agents=a.wire_agents, apply=a.apply, adopt_receipt=a.adopt_receipt, shared_runner=a.shared_runner)
    except (ValueError, OSError) as exc:
        print(f'Context Keeper install: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
