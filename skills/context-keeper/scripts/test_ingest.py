import os
import pathlib
import tempfile
import unittest

from contextkeeper.ingest import discover_files, extract_items, ingest, strip_marked
from contextkeeper.store import Store


class ExtractTests(unittest.TestCase):
    def test_heading_sets_the_kind(self):
        md = "# Rules\n## Constraints\n- Never send raw archive data to a provider\n"
        items = extract_items(md)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], "constraint")
        self.assertEqual(items[0]["anchor"], "Constraints")

    def test_line_words_decide_without_a_heading(self):
        items = extract_items("# Misc\n- Always pin dependency versions exactly\n")
        self.assertEqual(items[0]["kind"], "constraint")

    def test_decision_verb_is_a_decision(self):
        items = extract_items("# Notes\n- We use SQLite for local state\n")
        self.assertEqual(items[0]["kind"], "decision")

    def test_open_question_marked(self):
        items = extract_items("## Open questions\n- Should the importer stream or buffer?\n")
        self.assertEqual(items[0]["kind"], "question")

    def test_plain_item_is_a_note(self):
        items = extract_items("# Stuff\n- The parser handles zip files\n")
        self.assertEqual(items[0]["kind"], "note")

    def test_fenced_code_is_ignored(self):
        md = "# Run\n```powershell\npython thing.py add decision \"nope\"\n```\n- A real fact about the system\n"
        items = extract_items(md)
        texts = [i["text"] for i in items]
        self.assertEqual(len(items), 1)
        self.assertIn("real fact", texts[0])

    def test_shell_commands_are_not_records(self):
        md = "# Use\n- python -m pytest -q\n- npm run build\n- node --version\n"
        self.assertEqual(extract_items(md), [])

    def test_navigation_table_is_not_records(self):
        md = (
            "| Work | Read |\n|---|---|\n"
            "| Understand the tool | [README.md](README.md) |\n"
            "| Use it | [skill/SKILL.md](skill/SKILL.md) |\n"
        )
        self.assertEqual(extract_items(md), [])

    def test_content_table_becomes_records(self):
        md = "| Kind | Meaning |\n|---|---|\n| constraint | a hard rule you must not break |\n"
        items = extract_items(md)
        self.assertEqual(len(items), 1)
        self.assertIn("hard rule", items[0]["text"])

    def test_checkbox_open_is_state(self):
        items = extract_items("- [ ] Port the importer to the new schema\n- [x] Ship v1\n")
        self.assertTrue(all(i["kind"] == "state" for i in items))

    def test_wrapped_bullet_joins_into_one_record(self):
        md = (
            "## Constraints\n"
            "1. Never delete. `correct` writes a new record and marks the old one\n"
            "   superseded. The original stays, with history.\n"
        )
        items = extract_items(md)
        self.assertEqual(len(items), 1)
        self.assertIn("superseded", items[0]["text"])
        self.assertIn("with history", items[0]["text"])

    def test_prose_at_column_zero_is_not_appended(self):
        md = (
            "- A real statement about the system here\n"
            "This is a paragraph, not a continuation.\n"
        )
        items = extract_items(md)
        self.assertEqual(items[0]["text"], "A real statement about the system here")

    def test_crlf_input_works(self):
        items = extract_items("# Rules\r\n- Never write raw data to disk\r\n")
        self.assertEqual(items[0]["kind"], "constraint")

    def test_short_or_empty_lines_dropped(self):
        self.assertEqual(extract_items("- ok\n- a\n"), [])


class MarkedBlockTests(unittest.TestCase):
    def test_context_keepers_own_block_is_stripped(self):
        md = (
            "# My Project\n"
            "<!-- context-keeper:begin -->\n"
            "## Context (Context Keeper)\n"
            "- Never edit or delete a record\n"
            "<!-- context-keeper:end -->\n"
            "- This is the real fact\n"
        )
        items = extract_items(strip_marked(md))
        texts = [i["text"] for i in items]
        self.assertEqual(len(items), 1)
        self.assertEqual(texts[0], "This is the real fact")

    def test_snapshot_comment_is_stripped(self):
        md = '# T\n- A real statement here\n<!-- context-keeper:snapshot {"1": "abc"} -->\n'
        self.assertNotIn("snapshot", strip_marked(md))


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.root = self.tmp / "proj"
        self.root.mkdir()
        (self.root / "AGENTS.md").write_text(
            "# Project\n\n## Constraints\n- Never send raw data to a provider\n\n"
            "## Decisions\n- We use SQLite for local state\n",
            encoding="utf-8",
        )
        self.db = str(self.tmp / "ctx.sqlite")
        self.s = Store(self.db)

    def tearDown(self):
        self.s.close()

    def test_ingest_adds_records_with_sources(self):
        report = ingest(self.s, self.root)
        self.assertEqual(report["totals"]["added"], 2)
        rows = self.s.current()
        self.assertEqual({r["kind"] for r in rows}, {"constraint", "decision"})
        # both records are linked to a source that names the file
        refs = [
            self.s.conn.execute("SELECT ref FROM source WHERE id=?", (r["source_id"],)).fetchone()["ref"]
            for r in rows
        ]
        self.assertTrue(all(ref.startswith("AGENTS.md") for ref in refs))
        self.assertTrue(any("#constraints" in ref for ref in refs))

    def test_ingest_is_idempotent(self):
        ingest(self.s, self.root)
        again = ingest(self.s, self.root)
        self.assertEqual(again["totals"]["added"], 0)
        self.assertEqual(again["totals"]["existing"], 2)
        self.assertEqual(len(self.s.current()), 2)

    def test_retired_record_is_not_resurrected(self):
        ingest(self.s, self.root)
        rid = [r["id"] for r in self.s.current() if r["kind"] == "constraint"][0]
        self.s.retire(rid, reason="no longer true")
        again = ingest(self.s, self.root)
        self.assertEqual(again["totals"]["added"], 0)
        self.assertNotIn(rid, [r["id"] for r in self.s.current()])

    def test_dry_run_writes_nothing(self):
        report = ingest(self.s, self.root, dry_run=True)
        self.assertEqual(report["totals"]["added"], 2)
        self.assertEqual(len(self.s.current()), 0)

    def test_changed_source_is_reported_not_silently_kept(self):
        ingest(self.s, self.root)
        # change the constraint line in the doc
        (self.root / "AGENTS.md").write_text(
            "# Project\n\n## Constraints\n- Never send raw data to anyone at all\n\n"
            "## Decisions\n- We use SQLite for local state\n",
            encoding="utf-8",
        )
        report = ingest(self.s, self.root)
        # the new wording is added, the old record is flagged as possibly stale
        self.assertEqual(report["totals"]["added"], 1)
        stale_texts = {rec["text"] for rec in report["stale"]}
        self.assertIn("Never send raw data to a provider", stale_texts)

    def test_scope_is_applied(self):
        ingest(self.s, self.root, scope="api")
        self.assertTrue(all(r["scope"] == "api" for r in self.s.current()))


class DiscoverTests(unittest.TestCase):
    def test_priority_files_and_docs_dirs(self):
        root = pathlib.Path(tempfile.mkdtemp())
        (root / "AGENTS.md").write_text("# a\n", encoding="utf-8")
        (root / "notes.md").write_text("# b\n", encoding="utf-8")
        (root / "docs").mkdir()
        (root / "docs" / "spec.md").write_text("# c\n", encoding="utf-8")
        (root / "node_modules").mkdir()
        (root / "node_modules" / "x.md").write_text("# d\n", encoding="utf-8")
        (root / "CHANGELOG.md").write_text("# e\n", encoding="utf-8")
        found, skipped = discover_files(root)
        rels = [rel for rel, _ in found]
        self.assertIn("AGENTS.md", rels)
        self.assertIn("notes.md", rels)
        self.assertIn("docs/spec.md", rels)
        self.assertNotIn("CHANGELOG.md", rels)
        self.assertFalse(any("node_modules" in r for r in rels))
        self.assertEqual(skipped, [])

    def test_large_file_is_skipped_with_a_reason(self):
        root = pathlib.Path(tempfile.mkdtemp())
        (root / "big.md").write_text("# T\n- " + "x" * 100 + "\n", encoding="utf-8")
        found, skipped = discover_files(root, max_file_bytes=10)
        self.assertEqual([r for r, _ in found if r == "big.md"], [])
        self.assertEqual(skipped[0]["file"], "big.md")
        self.assertEqual(skipped[0]["reason"], "too_large")
        self.assertIn("size", skipped[0])

    def test_sources_dir_is_scanned(self):
        root = pathlib.Path(tempfile.mkdtemp())
        (root / "sources").mkdir()
        (root / "sources" / "raw.md").write_text("# S\n- A real statement here\n", encoding="utf-8")
        rels = [rel for rel, _ in discover_files(root)[0]]
        self.assertIn("sources/raw.md", rels)


class SnapshotTests(unittest.TestCase):
    def test_snapshot_changes_when_text_is_edited(self):
        s = Store(str(pathlib.Path(tempfile.mkdtemp()) / "c.sqlite"))
        rid = s.add("fact", "version one")
        before = s.snapshot()
        # retire + re-add the same idea is a change the brief must notice
        s.retire(rid)
        s.add("fact", "version two")
        after = s.snapshot()
        self.assertNotEqual(before, after)
        s.close()


class IngestReportingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.root = self.tmp / "proj"
        self.root.mkdir()
        (self.root / "AGENTS.md").write_text(
            "# Project\n\n## Constraints\n- Never send raw archive data to a provider\n",
            encoding="utf-8",
        )
        self.s = Store(str(self.tmp / "ctx.sqlite"))

    def tearDown(self):
        self.s.close()

    def test_oversized_file_is_reported_not_silently_dropped(self):
        (self.root / "huge.md").write_text("# H\n- " + "x" * 200 + "\n", encoding="utf-8")
        report = ingest(self.s, self.root, max_file_bytes=50)
        reasons = {sk["reason"] for sk in report["skipped"]}
        self.assertIn("too_large", reasons)
        self.assertTrue(any(sk["file"] == "huge.md" for sk in report["skipped"]))

    def test_near_duplicate_is_reported_and_not_added(self):
        ingest(self.s, self.root)
        before = len(self.s.current())
        (self.root / "notes.md").write_text(
            "# Notes\n- Never send raw archive data to a provider anywhere\n",
            encoding="utf-8",
        )
        report = ingest(self.s, self.root)
        self.assertEqual(report["totals"]["duplicates"], 1)
        self.assertEqual(report["totals"]["added"], 0)
        self.assertEqual(len(self.s.current()), before)
        self.assertEqual(report["duplicates"][0]["kind"], "constraint")


class SourceSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.root = self.tmp / "proj"
        self.root.mkdir()
        self.file = self.root / "AGENTS.md"
        self.file.write_text(
            "# Project\n\n## Constraints\n- Never send raw archive data to a provider\n",
            encoding="utf-8",
        )
        self.s = Store(str(self.tmp / "ctx.sqlite"))

    def tearDown(self):
        self.s.close()

    def test_manual_reference_is_not_flagged_stale(self):
        ingest(self.s, self.root)  # establishes the checked source for AGENTS.md
        ref = self.s.find_or_add_source("AGENTS.md", note="manual", checked=False)
        rid = self.s.add("fact", "a hand-added note that is not in the file", source_id=ref)
        report = ingest(self.s, self.root)
        self.assertNotIn(rid, {x["id"] for x in report["stale"]})

    def test_ingested_record_is_flagged_when_its_source_changes(self):
        ingest(self.s, self.root)
        self.file.write_text(
            "# Project\n\n## Constraints\n- Never send raw archive data to anyone at all\n",
            encoding="utf-8",
        )
        report = ingest(self.s, self.root)
        self.assertTrue(any("to a provider" in x["text"] for x in report["stale"]))


if __name__ == "__main__":
    unittest.main()
