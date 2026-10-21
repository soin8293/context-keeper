import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('release_check',Path(__file__).resolve().parents[1]/'scripts/check_release.py')
checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)


class ReleaseContentTests(unittest.TestCase):
    def test_nonempty_linked_documents_and_duplicate_anchors(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'README.md').write_text('# Start\n[Details](guide.md#details-1)\n',encoding='utf-8')
            (root/'guide.md').write_text('# Details\nFirst section.\n## Details\nSecond section.\n',encoding='utf-8')
            self.assertEqual(checker.inspect_files(root,['README.md','guide.md']),[])

    def test_empty_document_missing_link_and_bad_anchor_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'README.md').write_text('# Start\n[Broken](missing.md)\n[Anchor](guide.md#absent)\n',encoding='utf-8')
            (root/'guide.md').write_text('# Details\nComplete content.\n',encoding='utf-8')
            (root/'architecture.md').write_text('',encoding='utf-8')
            kinds={r['kind']for r in checker.inspect_files(root,['README.md','guide.md','architecture.md'])}
            self.assertEqual(kinds,{'missing-local-link','missing-local-anchor','empty-file'})

    def test_private_data_paths_and_unfilled_templates_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'context.sqlite').write_bytes(b'private fixture')
            machine='C:'+chr(92)+'Users'+chr(92)+'fixture'+chr(92)+'project'
            (root/'README.md').write_text('# {{PRODUCT_NAME}}\n'+machine+'\n',encoding='utf-8')
            kinds={r['kind']for r in checker.inspect_files(root,['README.md','context.sqlite'])}
            self.assertEqual(kinds,{'private-data-format','source-machine-path','unresolved-template'})

    def test_fenced_example_links_are_not_treated_as_document_navigation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'README.md').write_text('# Usage\n```text\n[example](not-an-actual-file.md)\n```\n',encoding='utf-8')
            self.assertEqual(checker.inspect_files(root,['README.md']),[])


if __name__=='__main__':unittest.main()
