"""Regressions for recorded fence and invalid-brief failures."""
from argparse import Namespace
from contextlib import redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from contextkeeper import cli
from contextkeeper.ingest import extract_items


class UsageRepairTests(unittest.TestCase):
    def test_tilde_fence_excludes_code_and_retains_following_fact(self):
        text = '# Facts\n~~~text\n- Not an actual project fact\n~~~\n- The parser supports local records\n'
        self.assertEqual([r['text'] for r in extract_items(text)], ['The parser supports local records'])

    def test_other_fence_type_does_not_close_a_code_block(self):
        text = '````text\n~~~\n- Still code inside original block\n```\n- A shorter fence cannot close it\n````\n- A real retained project statement\n'
        self.assertEqual([r['text'] for r in extract_items(text)], ['A real retained project statement'])

    def test_longer_tilde_closer_is_supported(self):
        text = '~~~text\n- Ignore this code example\n~~~~\n- Keep this actual project statement\n'
        self.assertEqual(len(extract_items(text)), 1)

    def test_missing_brief_returns_two_without_opening_store(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(cli, '_store') as store, redirect_stderr(io.StringIO()):
            self.assertEqual(cli.cmd_check(Namespace(brief=str(Path(temp) / 'missing.md'))), 2)
            store.assert_not_called()

    def test_invalid_brief_returns_two_without_opening_store(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(cli, '_store') as store, redirect_stderr(io.StringIO()):
            path = Path(temp) / 'invalid.md'
            path.write_bytes(b'not a saved context brief')
            self.assertEqual(cli.cmd_check(Namespace(brief=str(path))), 2)
            path.write_bytes(b'\xff\xfe')
            self.assertEqual(cli.cmd_check(Namespace(brief=str(path))), 2)
            store.assert_not_called()


if __name__ == '__main__':
    unittest.main()
