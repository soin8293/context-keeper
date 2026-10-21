"""Regressions for recovered runtime packaging and explicit project installation."""
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import install
from contextkeeper import cli
from contextkeeper.ingest import ingest, MAX_ITEMS_PER_FILE
from contextkeeper.store import Store


class PackagedContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        (self.project / 'README.md').write_text('# Decisions\n- We use the alpha adapter for parsing records\n', encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def wire(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            return install.wire_project(self.project, wire_agents=False, **kwargs)

    def test_preview_does_not_create_a_store(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(install.main(['project', str(self.project)]), 0)
        self.assertFalse((self.project / '.context-keeper').exists())

    def test_runner_is_anchored_when_launched_from_another_directory(self):
        self.wire()
        notes = json.loads((self.project / '.context-keeper/context.agent.json').read_text())
        self.assertTrue(notes['writes'].startswith('Use the project-owned'))
        outside = self.root / 'elsewhere'
        outside.mkdir()
        result = subprocess.run([sys.executable, str(self.project / '.context-keeper/ck.py'), 'status'],
                                cwd=outside, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('current records: 1', result.stdout)
        self.assertFalse((outside / '.context-keeper').exists())

    def test_runtime_update_preserves_database_and_rejects_local_code_edits(self):
        self.wire()
        db = self.project / '.context-keeper/context.sqlite'
        before = hashlib.sha256(db.read_bytes()).hexdigest()
        self.wire(do_ingest=False)
        self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)
        runtime = self.project / '.context-keeper/contextkeeper/cli.py'
        runtime.write_text(runtime.read_text(encoding='utf-8')+'\n# local edit\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'local edits'):
            self.wire(do_ingest=False)
        self.assertTrue(runtime.read_text(encoding='utf-8').endswith('# local edit\n'))

    def test_unrecognized_runtime_is_not_replaced(self):
        local = self.project / '.context-keeper'
        local.mkdir()
        (local / 'ck.py').write_text('# original project tool\n')
        with self.assertRaisesRegex(ValueError, 'no receipt'):
            self.wire()

    def test_unrecognized_store_and_edited_router_are_preserved(self):
        local = self.project / '.context-keeper'
        local.mkdir()
        db = local / 'context.sqlite'
        db.write_bytes(b'unrecognized archive: do not alter')
        with self.assertRaisesRegex(ValueError, 'no receipt'):
            self.wire()
        self.assertEqual(db.read_bytes(), b'unrecognized archive: do not alter')
        db.unlink()
        self.wire()
        router = local / 'CONTEXT.md'
        router.write_text('Custom local instructions', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'router has local edits'):
            self.wire()
        self.assertEqual(router.read_text(), 'Custom local instructions')

    def test_bad_markers_fail_before_any_runtime_is_written(self):
        for text in [install.BEGIN, install.END+'\n'+install.BEGIN]:
            (self.project / 'AGENTS.md').write_text(text, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'markers'):
                install.wire_project(self.project, wire_agents=True)
            self.assertFalse((self.project / '.context-keeper').exists())

    def test_item_cap_is_reported(self):
        lines = ['# Facts'] + [f'- Record item has unique identifier word{i}' for i in range(MAX_ITEMS_PER_FILE+5)]
        (self.project / 'README.md').write_text('\n'.join(lines), encoding='utf-8')
        s = Store(str(self.root / 'synthetic.sqlite'))
        try:
            result = ingest(s, self.project)
            limits = [r for r in result['skipped'] if r['reason']=='item_limit']
            self.assertEqual(limits[0]['omitted_items'], 5)
        finally:
            s.close()

    def test_deleted_checked_source_is_reported(self):
        s = Store(str(self.root / 'synthetic.sqlite'))
        try:
            ingest(s, self.project)
            (self.project / 'README.md').unlink()
            self.assertTrue(ingest(s, self.project)['stale'])
        finally:
            s.close()

    def test_brief_check_detects_source_drift_without_writing_records(self):
        self.wire()
        runner = self.project / '.context-keeper/ck.py'
        def run(*args):
            return subprocess.run([sys.executable, str(runner), *args], capture_output=True, text=True)
        self.assertEqual(run('brief', 'adapter', '--output', '.context-keeper/briefs/v1.md').returncode, 0)
        self.assertEqual(run('check', '.context-keeper/briefs/v1.md').returncode, 0)
        (self.project / 'README.md').write_text('# Decisions\n- We use the beta adapter for parsing records\n', encoding='utf-8')
        db = self.project / '.context-keeper/context.sqlite'
        before = db.read_bytes()
        result = run('check', '.context-keeper/briefs/v1.md')
        self.assertEqual(result.returncode, 1, result.stdout+result.stderr)
        self.assertIn('STALE', result.stdout)
        self.assertEqual(db.read_bytes(), before)

    def test_missing_store_query_does_not_create_a_database(self):
        db = self.root / 'absent.sqlite'
        with redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--db', str(db), 'status']), 2)
        self.assertFalse(db.exists())

    def test_snapshot_detects_changed_scope_in_a_synthetic_store(self):
        s = Store(str(self.root / 'synthetic.sqlite'))
        try:
            rid = s.add('fact', 'Synthetic scope-bound fact')
            before = s.snapshot()
            # Fixture mutation simulates an existing tool changing only a binding.
            s.conn.execute('UPDATE record SET scope=? WHERE id=?', ('api', rid))
            s.conn.commit()
            self.assertNotEqual(before, s.snapshot())
        finally:
            s.close()

    def test_reviewed_external_receipt_adopts_without_replacing_database(self):
        self.wire()
        local=self.project/'.context-keeper'
        receipt=local/'.runtime-install.json'
        external=self.root/'verified-legacy.json'
        external.write_bytes(receipt.read_bytes())
        receipt.unlink()
        before=(local/'context.sqlite').read_bytes()
        with redirect_stdout(io.StringIO()):
            install.wire_project(self.project,do_ingest=False,wire_agents=False,adopt_receipt=external,apply=False)
        self.assertFalse(receipt.exists())
        with redirect_stdout(io.StringIO()):
            install.wire_project(self.project,do_ingest=False,wire_agents=False,adopt_receipt=external)
        self.assertEqual((local/'context.sqlite').read_bytes(),before)
        self.assertTrue(receipt.exists())
        self.assertTrue(list((local/'backups').glob('*/.runtime-install.json')))

    def test_adoption_does_not_bypass_changed_runtime_or_existing_receipt(self):
        self.wire()
        local=self.project/'.context-keeper'
        receipt=local/'.runtime-install.json'
        external=self.root/'verified-legacy.json'
        external.write_bytes(receipt.read_bytes())
        with self.assertRaisesRegex(ValueError,'already has a receipt'):
            install.wire_project(self.project,adopt_receipt=external)
        receipt.unlink()
        code=local/'contextkeeper/cli.py'
        code.write_text(code.read_text(encoding='utf-8')+'\n# later local edit\n',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'local edits'):
            install.wire_project(self.project,adopt_receipt=external)
        self.assertFalse(receipt.exists())

    def test_project_maintenance_gate_blocks_runner_before_any_database_access(self):
        self.wire()
        local=self.project/'.context-keeper'
        before=(local/'context.sqlite').read_bytes()
        (local/'.maintenance').write_text('Owner-controlled bounded upgrade',encoding='utf-8')
        result=subprocess.run([sys.executable,str(local/'ck.py'),'status'],capture_output=True,text=True)
        self.assertEqual(result.returncode,75)
        self.assertIn('maintenance',result.stderr)
        self.assertEqual((local/'context.sqlite').read_bytes(),before)
        (local/'.maintenance').unlink()
        result=subprocess.run([sys.executable,str(local/'ck.py'),'status'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_shared_runner_preserves_caller_source_paths_and_pins_existing_store(self):
        with redirect_stdout(io.StringIO()):
            install.wire_project(self.project,do_ingest=False,wire_agents=False,shared_runner=True)
        local=self.project/'.context-keeper'
        caller=self.root/'other-project'
        caller.mkdir()
        (caller/'DECISIONS.md').write_text('## Decisions\nThe caller uses an isolated parser trial.',encoding='utf-8')
        result=subprocess.run([sys.executable,str(local/'ck.py'),'ingest','.'],cwd=caller,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr)
        s=Store(str(local/'context.sqlite'),read_only=True)
        try:
            self.assertEqual(s.current()[0]['text'],'The caller uses an isolated parser trial.')
            self.assertEqual(s.conn.execute('SELECT origin FROM source').fetchone()[0],str(caller.resolve()))
        finally:
            s.close()
        self.assertFalse((caller/'.context-keeper').exists())

    def test_shared_runner_mode_survives_a_recognized_update(self):
        with redirect_stdout(io.StringIO()):
            install.wire_project(self.project,do_ingest=False,wire_agents=False,shared_runner=True)
            install.wire_project(self.project,do_ingest=False,wire_agents=False)
        receipt=json.loads((self.project/'.context-keeper/.runtime-install.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['runner_mode'],'shared')
        self.assertIn("sys.argv[1:1]",(self.project/'.context-keeper/ck.py').read_text(encoding='utf-8'))

    def test_legacy_inspection_is_file_only_and_adoption_receipt_is_reviewable(self):
        self.wire()
        local=self.project/'.context-keeper'
        before=(local/'context.sqlite').read_bytes()
        output=self.root/'review-receipt.json'
        with redirect_stdout(io.StringIO()):
            self.assertEqual(install.main(['inspect-legacy',str(self.project),'--output',str(output)]),0)
        self.assertEqual((local/'context.sqlite').read_bytes(),before)
        payload=json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(payload['files'],install.file_hashes(local/'contextkeeper'))
        self.assertTrue(payload['review_required'])
        self.assertFalse(payload['database_opened'])
        with self.assertRaisesRegex(ValueError,'new external'):
            install.inspect_legacy(self.project,output)

    def test_legacy_inspection_rejects_receipt_inside_context_directory(self):
        self.wire()
        with self.assertRaisesRegex(ValueError,'new external'):
            install.inspect_legacy(self.project,self.project/'.context-keeper/review.json')


if __name__ == '__main__':
    unittest.main(verbosity=2)
