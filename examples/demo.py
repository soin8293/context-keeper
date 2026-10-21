"""Reproduce a synthetic source-linked handoff with the actual project runner."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import sys

REPO=Path(__file__).resolve().parents[1]
SCRIPTS=REPO/'skills/context-keeper/scripts'
sys.path.insert(0,str(SCRIPTS))
from contextkeeper.store import Store


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args(argv)
    work=args.directory.resolve()
    marker=work/'.context-keeper-demo'
    if work.exists() and not marker.exists() and any(work.iterdir()):
        raise ValueError('Use a new/empty directory; unrelated data will not be replaced.')
    work.mkdir(parents=True,exist_ok=True)
    if not marker.exists():
        for directory in ('global','review','build'):
            shutil.copytree(REPO/'examples/project'/directory,work/directory)
        marker.write_text('Synthetic Context Keeper demo v0.4.1\n',encoding='utf-8')
    runner=work/'.context-keeper/ck.py'
    def call(*command,expected=0):
        result=subprocess.run([sys.executable,'-B','-X','utf8',*map(str,command)],cwd=REPO,capture_output=True,text=True,encoding='utf-8')
        if result.returncode!=expected:
            raise RuntimeError(f'Unexpected exit {result.returncode}, expected {expected}: {command}\n{result.stdout}\n{result.stderr}')
        return result
    if not runner.exists():
        call(SCRIPTS/'install.py','project',work,'--apply','--no-ingest')
    if args.prepare_only:
        print(json.dumps({'prepared':str(work),'database':str(work/'.context-keeper/context.sqlite'),'next':'Inspect your host-required database overview/notes, then run this demo without --prepare-only.'}))
        return 0
    receipt=work/'demo-result.json'
    if receipt.exists():
        raise ValueError('Demo already ran; retain its artifacts and choose a new directory.')
    db=work/'.context-keeper/context.sqlite'
    call(runner,'add','constraint','Keep secrets and personal data local.','--mandatory','--source','GUARDRAILS.md#constraints','--source-checked','--source-root',work/'global')
    call(runner,'ingest',work/'review','--scope','review')
    call(runner,'ingest',work/'build','--scope','build')
    store=Store(str(db),read_only=True)
    try:
        records=store.current()
        base=next(r['id']for r in records if r['text'].startswith('Retain local audit logs'))
        amendment=next(r['id']for r in records if r['text'].startswith('The final report must stay local'))
        approval=next(r['id']for r in records if r['text'].startswith('The owner approves'))
    finally:store.close()
    call(runner,'amend',base,amendment,'--reason','Only the report-publication clause changes; audit-log retention remains required.')
    full=work/'.context-keeper/briefs/handoff-v1.md'
    tight=work/'.context-keeper/briefs/tight-v1.md'
    call(runner,'brief','builder resuming the adapter trial','--scope','review','--scope','build','--require',approval,'--require',amendment,'--output-budget','6000','--output',full)
    call(runner,'check',full)
    call(runner,'brief','builder resuming the adapter trial','--scope','review','--scope','build','--require',approval,'--require',amendment,'--budget','100','--output-budget','6000','--output',tight,expected=1)
    before=hashlib.sha256(db.read_bytes()).hexdigest()
    call(runner,'status')
    assert hashlib.sha256(db.read_bytes()).hexdigest()==before
    source=work/'review/DECISIONS.md'
    original=source.read_bytes()
    try:
        source.write_bytes(original+b'\n# Narrative\nA new uncaptured source caveat.\n')
        call(runner,'check',full,expected=1)
    finally:source.write_bytes(original)
    call(runner,'check',full)
    text=full.read_text(encoding='utf-8')
    assert len(text)<=6000 and 'Partly amended by' in text and '**Included:** 5 of 5' in text
    assert 'INCOMPLETE' in tight.read_text(encoding='utf-8')
    result={'synthetic_records':len(records),'handoff_chars':len(text),'output_cap':6000,
            'normal_check_exit':0,'tight_brief_exit':1,'changed_source_check_exit':1,
            'query_database_bytes_unchanged':True,'full_handoff':str(full),'tight_handoff':str(tight)}
    receipt.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))
    return 0


if __name__=='__main__':raise SystemExit(main())
