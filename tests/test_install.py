import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "scripts/skills.py"
spec = importlib.util.spec_from_file_location("skills_manager", path)
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class InstallerTests(unittest.TestCase):
    def test_windows_rename_failure_uses_verified_external_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'skills'
            manager.install('context-keeper',root)
            original=Path.rename
            locked_target=(root/'context-keeper').resolve()
            def deny_target(path, dest):
                # Windows hosted temp paths can use an 8.3 alias; the installer
                # resolves its root before calling rename.
                if path.resolve() == locked_target:
                    raise PermissionError('simulated Windows open-directory lock')
                return original(path,dest)
            with patch.object(Path,'rename',deny_target):
                result=manager.install('context-keeper',root)
            self.assertEqual(result['mode'],'guarded-file-update')
            backup=Path(result['backup'])
            self.assertFalse(backup.is_relative_to(root))
            self.assertEqual(manager.hashes(backup),manager.hashes(root/'context-keeper'))
            self.assertEqual(json.loads((root/'context-keeper'/manager.RECEIPT).read_text())['files'],manager.hashes(root/'context-keeper'))

    def test_stage_rename_failure_restores_then_updates_existing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'skills'
            manager.install('context-keeper',root)
            original=Path.rename
            def deny_stage(path,dest):
                if path.parent.name=='skill-install-staging':
                    raise PermissionError('simulated stage rename denied')
                return original(path,dest)
            with patch.object(Path,'rename',deny_stage):
                result=manager.install('context-keeper',root)
            self.assertEqual(result['mode'],'guarded-file-update')
            self.assertEqual(manager.hashes(root/'context-keeper'),manager.hashes(manager.catalog()['context-keeper']))

    def test_fallback_failed_file_copy_restores_original_bytes_receipt_and_new_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            target,stage,backup=(base/n for n in ('target','stage','backup'))
            target.mkdir(); stage.mkdir()
            (target/'old.txt').write_text('preserve original')
            (target/manager.RECEIPT).write_text('old receipt')
            (stage/'old.txt').write_text('replacement')
            (stage/'new.txt').write_text('new')
            (stage/manager.RECEIPT).write_text('new receipt')
            old,new=manager.hashes(target),manager.hashes(stage)
            original=manager.shutil.copy2
            def fail_once(src,dest,*args,**kwargs):
                if Path(src)==stage/'new.txt':
                    raise OSError('simulated transfer failure')
                return original(src,dest,*args,**kwargs)
            with patch.object(manager.shutil,'copy2',side_effect=fail_once):
                with self.assertRaises(OSError):
                    manager.guarded_file_update(stage,target,backup,old,new)
            self.assertEqual(manager.hashes(target),old)
            self.assertEqual((target/manager.RECEIPT).read_text(),'old receipt')
            self.assertFalse((target/'new.txt').exists())

    def test_fallback_rejects_racing_local_edit_before_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            target,stage=(base/n for n in ('target','stage'))
            target.mkdir(); stage.mkdir()
            (target/'local.txt').write_text('before')
            old=manager.hashes(target)
            (target/'local.txt').write_text('new local work')
            with self.assertRaisesRegex(ValueError,'local edits'):
                manager.guarded_file_update(stage,target,base/'backup',old,{})
            self.assertEqual((target/'local.txt').read_text(),'new local work')
            self.assertFalse((base/'backup').exists())

    def test_script_only_test_file_cannot_report_a_green_suite(self):
        runner = path.parent / 'run_suite.py'
        with tempfile.TemporaryDirectory() as tmp:
            test = Path(tmp) / 'test_scenarios.py'
            test.write_text('def main():\n    assert True\n', encoding='utf-8')
            result = subprocess.run([sys.executable, str(runner), tmp], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('No discoverable tests', result.stderr)
            test.write_text('import unittest\nclass RealTests(unittest.TestCase):\n    def test_example(self):\n        self.assertTrue(True)\n', encoding='utf-8')
            result = subprocess.run([sys.executable, str(runner), tmp], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn('Discovered 1 tests', result.stdout)

    def test_discovery_validation_and_named_install(self):
        self.assertIn("context-keeper", manager.catalog())
        manager.validate_skill(manager.catalog()["context-keeper"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills"
            result = manager.install("context-keeper", root)
            dest = root / "context-keeper"
            self.assertEqual(manager.hashes(dest), manager.hashes(manager.catalog()["context-keeper"]))
            self.assertFalse((dest / "tests/test_install.py").exists())
            self.assertIsNone(result["backup"])
            result = manager.install("context-keeper", root)
            self.assertTrue(Path(result["backup"]).is_dir())
            self.assertFalse(Path(result["backup"]).is_relative_to(root))

    def test_local_edits_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills"
            manager.install("context-keeper", root)
            f = root / "context-keeper/SKILL.md"
            f.write_text(f.read_text(encoding="utf-8") + "\nLocal edit\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "local edits"):
                manager.install("context-keeper", root)
            self.assertIn("Local edit", f.read_text(encoding="utf-8"))

    def test_receipt_required_and_external_adoption_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills"
            manager.install("context-keeper", root)
            receipt = root / "context-keeper" / manager.RECEIPT
            legacy = Path(tmp) / "legacy.json"
            legacy.write_bytes(receipt.read_bytes())
            receipt.unlink()
            with self.assertRaisesRegex(ValueError, "no receipt"):
                manager.install("context-keeper", root)
            result = manager.install("context-keeper", root, legacy)
            self.assertEqual(result["hashes"], "match source")
            payload = json.loads(legacy.read_text(encoding="utf-8"))
            payload["files"]["SKILL.md"] = "wrong hash"
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "local edits"):
                manager.install("context-keeper", root, legacy)


if __name__ == "__main__":
    unittest.main()
