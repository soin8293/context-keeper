"""Pure-parser regressions for interrupted and adjacent Markdown tables."""
import unittest

from contextkeeper.ingest import extract_items


class TableBoundaryTests(unittest.TestCase):
    def texts(self, markdown):
        return [record['text'] for record in extract_items(markdown)]

    def test_blank_lines_between_data_rows_keep_every_decision(self):
        markdown = (
            '# Decisions\n| ID | Choice |\n|---|---|\n'
            '| D-001 | First accepted choice |\n\n'
            '| D-002 | Second accepted choice |\n \t\n\n'
            '| D-003 | Third accepted choice |\n'
        )
        records = extract_items(markdown)
        self.assertEqual([r['text'].split(' — ')[0] for r in records],
                         ['D-001', 'D-002', 'D-003'])
        self.assertTrue(all(r['kind'] == 'decision' and r['anchor'] == 'Decisions'
                            for r in records))

    def test_new_table_header_after_blank_is_not_a_record(self):
        markdown = (
            '| ID | Choice |\n|---|---|\n| D-001 | First accepted choice |\n\n'
            '| Code | Meaning |\n|:---|---:|\n| R-002 | Second table decision |\n'
        )
        self.assertEqual(self.texts(markdown),
                         ['D-001 — First accepted choice', 'R-002 — Second table decision'])

    def test_adjacent_table_header_with_separator_is_not_data(self):
        markdown = (
            '| ID | Choice |\n|---|---|\n| D-001 | First accepted choice |\n'
            '| Code | Meaning |\n|---|---|\n| R-002 | Second table decision |\n'
        )
        self.assertEqual(self.texts(markdown),
                         ['D-001 — First accepted choice', 'R-002 — Second table decision'])

    def test_separator_like_cell_does_not_drop_a_content_row(self):
        markdown = '| Name | Value |\n|---|---|\n| Backup retention decision | --- |\n'
        self.assertEqual(self.texts(markdown), ['Backup retention decision — ---'])

    def test_prose_heading_and_fence_boundaries_keep_headers_out(self):
        markdown = (
            '# Decisions\n| ID | Choice |\n|---|---|\n| A-001 | First accepted choice |\n'
            '\nThis paragraph ends the table.\n\n'
            '| Code | Meaning |\n|---|---|\n| B-001 | Second accepted choice |\n'
            '```text\n| C-001 | Never extract this code row |\n```\n'
            '## Facts\n| ID | Fact |\n|---|---|\n| F-001 | A supported factual statement |\n'
        )
        records = extract_items(markdown)
        self.assertEqual([r['text'].split(' — ')[0] for r in records],
                         ['A-001', 'This paragraph ends the table.', 'B-001', 'F-001'])
        self.assertEqual([r['anchor'] for r in records], ['Decisions', 'Decisions', 'Decisions', 'Facts'])

    def test_navigation_after_blank_is_excluded_but_content_survives(self):
        markdown = (
            '| Work | Read |\n|---|---|\n| Setup guide | [README.md](README.md) |\n\n'
            '| Policies | [docs/rules.md](docs/rules.md) |\n\n'
            '| ID | Choice |\n|---|---|\n| D-101 | Keep every supported decision |\n'
        )
        self.assertEqual(self.texts(markdown), ['D-101 — Keep every supported decision'])


if __name__ == '__main__':
    unittest.main()
