"""Synthetic replays of recorded capture/retrieval/freshness/ownership failures."""
from contextlib import redirect_stdout, redirect_stderr
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from contextkeeper import cli
from contextkeeper.brief import build_brief, diff_snapshot, extract_snapshot
from contextkeeper.freshness import compact_snapshot, source_issues
from contextkeeper.ingest import extract_items, ingest, acknowledge_source
from contextkeeper.store import ContextError, Store, migrate, migration_preview


class FunctionalRepairs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        self.db = self.root / 'context.sqlite'
        self.s = Store(str(self.db))

    def tearDown(self):
        self.s.close()
        self.temp.cleanup()

    def command(self, *args):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = cli.main(['--db', str(self.db), *args])
        return code, out.getvalue()

    def write(self, text, name='DECISIONS.md', root=None):
        path = (root or self.project) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_ingest_then_correct_reuses_captured_replacement_and_keeps_history(self):
        self.write('## Decisions\nRetain raw inputs for 7 days.\n')
        ingest(self.s, self.project, scope='build')
        old=self.s.current()[0]['id']
        self.write('## Decisions\nRetain raw inputs for 14 days.\n')
        ingest(self.s, self.project, scope='build')
        replacement=next(r['id'] for r in self.s.current() if '14 days' in r['text'])
        self.assertEqual(self.s.correct(old,'Retain raw inputs for 14 days.'),replacement)
        self.assertEqual([r['id'] for r in self.s.current()],[replacement])
        self.assertEqual(self.s.get(old)['superseded_by'],replacement)
        self.assertEqual(self.s.get(replacement)['supersedes'],old)
        self.assertTrue(self.s.history(old))
        self.assertTrue(any(h['field']=='supersedes' for h in self.s.history(replacement)))
        code,out=self.command('brief','retention','--scope','build')
        self.assertEqual(code,0)
        self.assertEqual(out.count('Retain raw inputs for 14 days.'),1)

    def test_reused_correction_retains_mandatory_policy_and_amendments(self):
        old=self.s.add('constraint','Original policy',mandatory=True)
        replacement=self.s.add('constraint','Revised policy')
        amendment=self.s.add('decision','Only the storage clause changes')
        self.s.amend(old,amendment,'Storage only')
        self.assertEqual(self.s.correct(old,'Revised policy'),replacement)
        self.assertTrue(self.s.get(replacement)['mandatory'])
        self.assertTrue(any(link['base_id']==replacement and link['amendment_id']==amendment for link in self.s.amendments()))

    def test_correction_identity_does_not_merge_other_sources_scopes_or_kinds(self):
        one=self.s.add_source('one.md',origin=str(self.project))
        two=self.s.add_source('two.md',origin=str(self.project))
        old=self.s.add('decision','Old ruling',scope='build',source_id=one)
        foreign=[self.s.add('decision','New ruling',scope='review',source_id=one),
                 self.s.add('decision','New ruling',scope='build',source_id=two),
                 self.s.add('fact','New ruling',scope='build',source_id=one)]
        replacement=self.s.correct(old,'New ruling')
        self.assertNotIn(replacement,foreign)
        self.assertTrue(all(self.s.get(i)['status']=='current' for i in foreign))

    def test_reuse_refuses_ambiguous_history_or_same_amendment_group_without_writes(self):
        for mode in ('history','group','duplicates'):
            with self.subTest(mode=mode):
                old=self.s.add('decision','Old '+mode)
                if mode=='history':
                    prior=self.s.add('decision','Earlier '+mode)
                    target=self.s.correct(prior,'New '+mode)
                else:
                    target=self.s.add('decision','New '+mode)
                    if mode=='group': self.s.amend(old,target,'Partial change')
                    else: self.s.add('decision','New '+mode)
                before=self.db.read_bytes()
                with self.assertRaises(ContextError):self.s.correct(old,'New '+mode)
                self.assertEqual(self.db.read_bytes(),before)
                self.assertEqual(self.s.get(old)['status'],'current')

    def test_native_read_commands_use_enforced_readonly_connection(self):
        self.s.add('decision', 'Use the local adapter', scope='build')
        brief = self.root / 'brief.md'
        self.assertEqual(self.command('brief', 'adapter', '--scope', 'build', '--output', str(brief))[0], 0)
        before = self.db.read_bytes(), sorted(p.name for p in self.root.iterdir())
        real = cli.Store
        def guarded(path, read_only=False):
            self.assertTrue(read_only)
            store = real(path, read_only=True)
            def deny(action, *rest):
                return sqlite3.SQLITE_DENY if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_ALTER_TABLE) else sqlite3.SQLITE_OK
            store.conn.set_authorizer(deny)
            return store
        with patch.object(cli, 'Store', side_effect=guarded):
            for args in [('search','adapter'), ('show','1'), ('status','--scope','build'), ('log',), ('brief','adapter'), ('check',str(brief)), ('ingest',str(self.project),'--dry-run'), ('reconcile','--json')]:
                self.assertEqual(self.command(*args)[0], 0, args)
        self.assertEqual(before, (self.db.read_bytes(), sorted(p.name for p in self.root.iterdir())))
        ro = Store(str(self.db), read_only=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                ro.add('fact', 'Forbidden write')
        finally:
            ro.close()

    def test_capabilities_needs_no_store(self):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(['--db', str(self.root/'missing'), 'capabilities']), 0)
        self.assertEqual(json.loads(out.getvalue())['schema'], 2)
        self.assertFalse((self.root/'missing').exists())

    def test_exact_readback_retains_corrected_text_status_and_history(self):
        old=self.s.add('decision','The original ruling.')
        new=self.s.correct(old,'The verified replacement ruling.')
        code,out=self.command('show',str(old))
        self.assertEqual(code,0)
        data=json.loads(out)
        self.assertEqual(data['record']['status'],'superseded')
        self.assertEqual(data['record']['superseded_by'],new)
        self.assertTrue(data['history'])

    def test_explicit_superseded_marker_is_review_lead_without_automatic_retirement(self):
        rid=self.s.add('decision','SUPERSEDED: an older mixed approval needs reconciliation.',scope='build')
        result=build_brief(self.s,'approval',scope='build')
        self.assertTrue(result['incomplete'])
        self.assertEqual(self.s.get(rid)['status'],'current')

    def test_governing_prose_captured_but_narrative_quotes_and_code_excluded(self):
        rows = extract_items('# Narrative\nAn unrelated historical paragraph.\n## Decisions\nWe chose the local parser\nwith a stable input contract.\n\nThe owner requires a review before release.\n> A quoted example must not become a ruling.\n~~~\nAn example in code is not a decision.\n~~~\n')
        self.assertEqual([r['text'] for r in rows], ['We chose the local parser with a stable input contract.', 'The owner requires a review before release.'])
        self.assertTrue(all(r['kind']=='decision' for r in rows))

    def test_bullet_table_prose_limits_consistent_and_final_record_not_clipped(self):
        for text in ['## Facts\n'+ '\n'.join(f'- Fact number {i} remains available' for i in range(206)),
                     '## Facts\n|Key|Value|\n|---|---|\n'+'\n'.join(f'|{i}|Fact number {i} remains available|' for i in range(206)),
                     '## Decisions\n'+'\n\n'.join(f'Decision number {i} remains available.' for i in range(206))]:
            self.assertEqual(len(extract_items(text)), 200)
            self.assertEqual(len(extract_items(text, None)), 206)
        self.assertEqual(extract_items('- First whole statement needs\n  this continuation.\n- Another complete statement\n', 1)[0]['text'], 'First whole statement needs this continuation.')

    def test_active_source_precedes_archive_and_configured_limit_is_visible(self):
        self.write('# Facts\n- Historical filler that is not the current ruling', 'archive.md')
        self.write('## Decisions\nThe owner chose a bounded local test.', 'docs/current.md')
        self.write(json.dumps({'active':['docs/current.md'], 'max_files':1, 'max_items':10}), '.context-keeper/sources.json')
        report = ingest(self.s, self.project)
        self.assertEqual([r['file'] for r in report['files']], ['docs/current.md'])
        self.assertTrue(any(r['reason']=='file_limit' for r in report['skipped']))
        self.assertIn('owner chose', self.s.current()[0]['text'])

    def test_scope_and_origin_identity_do_not_merge_same_relative_filename(self):
        other = self.root / 'other'
        other.mkdir()
        text = '## Decisions\nWe chose a reusable local parser for this project.'
        self.write(text)
        self.write(text, root=other)
        ingest(self.s, self.project, scope='review')
        ingest(self.s, self.project, scope='build')
        ingest(self.s, other, scope='review')
        self.assertEqual(len(self.s.current()), 3)
        srcs = list(self.s.conn.execute('SELECT * FROM source'))
        self.assertEqual(len({r['origin'] for r in srcs}), 2)
        rid = self.s.current('build')[0]['id']
        self.s.retire(rid)
        self.assertEqual(ingest(self.s,self.project,scope='build')['totals']['added'], 0)
        self.assertEqual(self.s.get(rid)['status'], 'retired')

    def test_unrelated_global_no_longer_displaces_98_character_task_rule(self):
        self.s.add('constraint', 'Typography guidance unrelated to adapter selection.'.ljust(56, '.'))
        local = self.s.add('decision', 'Use the adapter selected for the current parser task and preserve its existing validation boundary.'.ljust(98,'.'), scope='build')
        result = build_brief(self.s, 'parser adapter', scope='build', budget_chars=120)
        self.assertEqual(result['included'], [local])

    def test_multiple_scopes_and_mandatory_global_are_explicit(self):
        safety = self.s.add('constraint','Never expose private credentials.', mandatory=True)
        review = self.s.add('decision','Review approves a local adapter test.',scope='review')
        build = self.s.add('state','Build owns the adapter test.',scope='build')
        foreign = self.s.add('decision','Unrelated project uses another adapter.',scope='foreign')
        result = build_brief(self.s,'adapter',scope=['review','build'],global_policy='exclude')
        self.assertEqual(set(result['included']), {safety,review,build})
        self.assertNotIn(foreign,result['included'])
        self.assertEqual(result['coverage']['scope_excluded'],1)
        tiny = build_brief(self.s,'adapter',scope='build',budget_chars=10)
        self.assertTrue(tiny['incomplete'])

    def test_exclude_globals_also_applies_without_an_explicit_scope(self):
        ordinary=self.s.add('fact','An optional global observation.')
        mandatory=self.s.add('constraint','An explicit global safety policy.',mandatory=True)
        scoped=self.s.add('decision','The local adapter ruling.',scope='build')
        result=build_brief(self.s,'adapter',global_policy='exclude')
        self.assertEqual(set(result['included']),{mandatory,scoped})
        self.assertNotIn(ordinary,result['included'])

    def test_excluding_previously_ingested_source_requires_reconciliation(self):
        self.write('## Decisions\nThe historical adapter was selected.','docs/archive.md')
        ingest(self.s,self.project)
        self.write(json.dumps({'exclude':['docs/archive.md']}),'.context-keeper/sources.json')
        report=ingest(self.s,self.project,dry_run=True)
        self.assertEqual(report['stale'][0]['reason'],'record_source_not_scanned_in_active_selection')

    def test_generated_brief_outside_default_briefs_folder_does_not_self_invalidate(self):
        self.write('## Decisions\nUse the adapter for local work only.')
        ingest(self.s,self.project)
        path=self.project/'handoff.md'
        self.assertEqual(self.command('brief','adapter','--output',str(path))[0],0)
        self.assertEqual(self.command('check',str(path))[0],0)

    def test_partial_amendment_travels_with_base_across_scopes_or_marks_incomplete(self):
        base = self.s.add('decision','Keep local logs and upload final reports.',scope='build')
        new = self.s.add('decision','For this incident keep the final report local too.',scope='review')
        self.s.amend(base,new,'Only the report-upload clause is overridden; log retention stays valid.')
        result = build_brief(self.s,'logs',scope='build')
        self.assertEqual(set(result['included']),{base,new})
        self.assertEqual(self.s.get(base)['status'],'current')
        self.assertIn('Only the report-upload clause',result['text'])
        tiny = build_brief(self.s,'logs',scope='build',budget_chars=60)
        self.assertFalse(tiny['included'])
        self.assertTrue(tiny['incomplete'])
        corrected = self.s.correct(new,'The report stays local until owner approval.')
        repaired=build_brief(self.s,'logs',scope='build')
        self.assertIn(corrected,repaired['included'])
        self.assertNotIn(new,repaired['included'])
        self.assertFalse(repaired['incomplete'])
        self.s.retire(corrected)
        self.assertTrue(build_brief(self.s,'logs',scope='build')['incomplete'])

    def test_required_id_outside_scope_and_retired_requirement(self):
        rid=self.s.add('decision','A required ruling in another scope.',scope='review')
        result=build_brief(self.s,'task',scope='build',required=[rid])
        self.assertIn(rid,result['included'])
        self.assertEqual(result['coverage']['scope_excluded'],0)
        self.s.retire(rid)
        self.assertTrue(build_brief(self.s,'task',scope='build',required=[rid])['incomplete'])

    def test_packet_size_and_freshness_ignore_1500_unrelated_scope_records(self):
        self.s.add('decision','Keep the parser contract stable.',scope='build')
        before=build_brief(self.s,'parser',scope='build',budget_chars=120)
        # Bulk synthetic fixture setup, not a project write route.
        self.s.conn.executemany("INSERT INTO record(kind,scope,text,status,created_at,updated_at) VALUES ('fact','foreign',?,'current','fixture','fixture')",
                                [(f'Foreign project item {i}',) for i in range(1500)])
        self.s.conn.commit()
        after=build_brief(self.s,'parser',scope='build',budget_chars=120)
        self.assertLess(len(after['text'])-len(before['text']),20)
        self.assertEqual(extract_snapshot(before['text']),extract_snapshot(after['text']))
        self.s.add('decision','A new parser ruling.',scope='build')
        self.assertNotEqual(extract_snapshot(before['text']),compact_snapshot(self.s,'build'))

    def test_full_output_cap_and_whole_records(self):
        text='The complete adapter rule must remain intact. ' * 8
        for i in range(8):
            self.s.add('decision',text+str(i),scope='build')
        result=build_brief(self.s,'adapter',scope='build',output_chars=2000)
        self.assertLessEqual(len(result['text']),2000)
        self.assertTrue(any(o['reason']=='output_budget_exceeded' for o in result['omitted']))
        for rid in result['included']:
            self.assertIn(self.s.get(rid)['text'],result['text'])
        with self.assertRaises(ContextError):
            build_brief(self.s,'x'*3000,scope='build',output_chars=1000)

    def test_raw_uncaptured_change_invalidates_and_needs_explicit_review(self):
        path=self.write('## Decisions\n- We use the local adapter for parsing.\n# Narrative\nOld description.')
        ingest(self.s,self.project)
        before=compact_snapshot(self.s)
        path.write_text(path.read_text()+'\nA later uncaptured caveat.',encoding='utf-8')
        self.assertNotEqual(before,compact_snapshot(self.s))
        report=ingest(self.s,self.project)
        self.assertTrue(report['unresolved'])
        self.assertTrue(build_brief(self.s,'adapter')['incomplete'])
        acknowledge_source(self.s,self.project,'DECISIONS.md','','Reviewed narrative caveat; does not change this ruling.')
        self.assertFalse(source_issues(self.s))

    def test_changed_numeric_policy_is_reported_without_automatic_retirement(self):
        path=self.write('## Constraints\n- Always retain project records for 30 days after review.')
        ingest(self.s,self.project)
        old=self.s.current()[0]['id']
        path.write_text(path.read_text().replace('30','60'),encoding='utf-8')
        report=ingest(self.s,self.project)
        self.assertTrue(report['duplicates'])
        self.assertIn('60',report['duplicates'][0]['text'])
        self.assertEqual(self.s.get(old)['status'],'current')
        self.assertTrue(build_brief(self.s,'retention')['incomplete'])

    def test_source_metadata_binding_and_deleted_root_invalidate(self):
        self.write('## Decisions\nWe chose the bounded local adapter.')
        ingest(self.s,self.project)
        before=self.s.snapshot()
        self.s.conn.execute("UPDATE source SET ref='MISSING.md#decisions'")
        self.s.conn.commit()
        self.assertNotEqual(before,self.s.snapshot())
        self.assertTrue(source_issues(self.s))

    def test_resolvable_source_in_packet(self):
        path=self.write('## Decisions\nThe owner chose a local test before release.')
        ingest(self.s,self.project)
        result=build_brief(self.s,'release')
        self.assertIn(path.resolve().as_uri()+'#decisions',result['text'])

    def test_legacy_brief_metadata_still_parses_and_diffs(self):
        old={'1':'abc','2':'def'}
        self.assertEqual(extract_snapshot('<!-- context-keeper:snapshot '+json.dumps(old)+' -->'),old)
        self.assertEqual(diff_snapshot(old,{'2':'new','3':'ghi'})['removed_from_current'],[1])
        self.assertIsNone(extract_snapshot('<!-- context-keeper:snapshot {"version": 99} -->'))

    def test_source_config_escape_and_invalid_encoding_reported(self):
        self.write(json.dumps({'active':['../outside.md']}),'.context-keeper/sources.json')
        with self.assertRaises(ContextError):
            ingest(self.s,self.project)
        (self.project/'.context-keeper/sources.json').unlink()
        (self.project/'DECISIONS.md').write_bytes(b'\xff')
        self.assertEqual(ingest(self.s,self.project)['skipped'][0]['reason'],'unreadable_or_invalid_utf8')


class MigrationRepairs(unittest.TestCase):
    def test_preservation_manifest_covers_text_status_and_history_without_export(self):
        with tempfile.TemporaryDirectory() as temp:
            db=Path(temp)/'context.sqlite'
            s=Store(str(db))
            original=s.add('decision','Preserve the original private ruling.')
            replacement=s.correct(original,'Use the verified replacement.')
            before=migration_preview(db)['preservation']
            result=migrate(db)
            self.assertEqual(before,migration_preview(db)['preservation'])
            self.assertEqual(before,result['preservation'])
            self.assertNotIn('private ruling',json.dumps(before))
            self.assertEqual(before['record']['rows'],2)
            self.assertEqual(before['record_history']['rows'],3)
            s.retire(replacement)
            after=migration_preview(db)['preservation']
            self.assertNotEqual(before['record']['sha256'],after['record']['sha256'])
            self.assertNotEqual(before['record_history']['sha256'],after['record_history']['sha256'])
            s.close()

    def test_legacy_preview_no_writes_explicit_upgrade_keeps_history_and_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            db=Path(temp)/'legacy.sqlite'
            with sqlite3.connect(db) as conn:
                conn.executescript('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE source(id INTEGER PRIMARY KEY,ref TEXT,note TEXT,created_at TEXT); CREATE TABLE record(id INTEGER PRIMARY KEY,kind TEXT,scope TEXT,text TEXT,status TEXT,supersedes INTEGER,superseded_by INTEGER,source_id INTEGER,created_at TEXT,updated_at TEXT); CREATE TABLE record_history(id INTEGER PRIMARY KEY,record_id INTEGER,field TEXT,old_value TEXT,new_value TEXT,reason TEXT,changed_at TEXT); CREATE TABLE event(id INTEGER PRIMARY KEY,at TEXT,action TEXT,detail TEXT);')
                conn.execute("INSERT INTO source VALUES (1,'DECISIONS.md',NULL,'old')")
                conn.execute("INSERT INTO record VALUES (1,'decision','build','Retained original','retired',NULL,NULL,1,'old','old')")
            conn.close()
            before=db.read_bytes()
            self.assertEqual(migration_preview(db)['sources_requiring_explicit_origin'],1)
            with self.assertRaises(ContextError):
                Store(str(db),read_only=True)
            self.assertEqual(db.read_bytes(),before)
            with self.assertRaises(ContextError):
                migrate(db,source_origins={'999':temp})
            self.assertEqual(db.read_bytes(),before)
            result=migrate(db,source_origins={'1':temp})
            # SQLite backup is transaction-consistent, not byte-identical headers.
            with closing(sqlite3.connect(Path(result['backup']).as_uri()+'?mode=ro',uri=True)) as backup:
                self.assertEqual(backup.execute('SELECT text,status FROM record').fetchone(),('Retained original','retired'))
                self.assertNotIn('origin',{r[1] for r in backup.execute('PRAGMA table_info(source)')})
            s=Store(str(db),read_only=True)
            try:
                self.assertEqual(s.get(1)['text'],'Retained original')
                self.assertEqual(s.get(1)['status'],'retired')
                self.assertEqual(s.conn.execute('SELECT origin FROM source').fetchone()[0],str(Path(temp).resolve()))
            finally:
                s.close()


if __name__=='__main__':
    unittest.main()
