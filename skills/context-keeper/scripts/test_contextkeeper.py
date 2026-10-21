import json
import os
import tempfile
import unittest

from contextkeeper.brief import build_brief, diff_snapshot, extract_snapshot
from contextkeeper.store import ContextError, Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.s = Store(os.path.join(self.tmp, "ctx.sqlite"))

    def tearDown(self):
        self.s.close()

    def test_add_and_get(self):
        rid = self.s.add("decision", "Use Postgres", scope="api")
        row = self.s.get(rid)
        self.assertEqual(row["kind"], "decision")
        self.assertEqual(row["status"], "current")
        self.assertEqual(row["scope"], "api")

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ContextError):
            self.s.add("banana", "nope")

    def test_empty_text_rejected(self):
        with self.assertRaises(ContextError):
            self.s.add("note", "   ")

    def test_correction_keeps_original(self):
        old = self.s.add("decision", "Use Postgres", scope="api")
        new = self.s.correct(old, "Use SQLite instead", reason="simpler")
        # original is kept, not deleted
        self.assertEqual(self.s.get(old)["status"], "superseded")
        self.assertEqual(self.s.get(old)["superseded_by"], new)
        # new record is current and points back
        self.assertEqual(self.s.get(new)["status"], "current")
        self.assertEqual(self.s.get(new)["supersedes"], old)
        # current view contains only the new decision
        current_ids = [r["id"] for r in self.s.current("api")]
        self.assertIn(new, current_ids)
        self.assertNotIn(old, current_ids)
        # history records the transition
        fields = [h["field"] for h in self.s.history(old)]
        self.assertIn("status", fields)

    def test_cannot_correct_twice(self):
        old = self.s.add("fact", "a")
        self.s.correct(old, "b")
        with self.assertRaises(ContextError):
            self.s.correct(old, "c")

    def test_scope_filter_includes_global(self):
        self.s.add("decision", "global rule", scope="")
        self.s.add("decision", "api rule", scope="api")
        self.s.add("decision", "web rule", scope="web")
        ids = {r["text"] for r in self.s.current("api")}
        self.assertEqual(ids, {"global rule", "api rule"})

    def test_retire(self):
        rid = self.s.add("state", "old phase")
        self.s.retire(rid, reason="done")
        self.assertEqual(self.s.get(rid)["status"], "retired")
        self.assertNotIn(rid, [r["id"] for r in self.s.current()])


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.s = Store(os.path.join(self.tmp, "ctx.sqlite"))
        self.s.add("constraint", "Never send raw archive data to a provider")
        self.s.add("decision", "Use SQLite for local state", scope="api")
        self.s.add("fact", "The parser handles zip files")
        self.s.add("note", "unrelated filler " + "x" * 200)

    def tearDown(self):
        self.s.close()

    def test_constraints_and_decisions_included(self):
        r = build_brief(self.s, "work on the parser", budget_chars=8000)
        self.assertIn("Never send raw archive", r["text"])
        self.assertIn("Use SQLite", r["text"])
        self.assertIn("## Constraints", r["text"])

    def test_budget_omits_whole_records_and_reports(self):
        r = build_brief(self.s, "anything", budget_chars=90)
        self.assertTrue(len(r["omitted"]) >= 1)
        for o in r["omitted"]:
            self.assertEqual(o["reason"], "char_budget_exceeded")
            self.assertGreater(o["size"], 0)
        self.assertIn("## Omitted", r["text"])

    def test_snapshot_roundtrip_and_diff(self):
        r = build_brief(self.s, "task", budget_chars=8000)
        snap = extract_snapshot(r["text"])
        self.assertIsNotNone(snap)
        self.assertTrue(diff_snapshot(snap, self.s.snapshot())["fresh"])
        # a new record makes the old brief stale
        self.s.add("decision", "a brand new rule")
        d = diff_snapshot(snap, self.s.snapshot())
        self.assertFalse(d["fresh"])
        self.assertTrue(d['compact'])  # v2 stores a digest rather than an unbounded ID inventory

    def test_correction_makes_brief_stale_and_hides_old_text(self):
        r = build_brief(self.s, "task", budget_chars=8000)
        snap = extract_snapshot(r["text"])
        # correct the SQLite decision
        old = [x["id"] for x in self.s.current() if "SQLite" in x["text"]][0]
        self.s.correct(old, "Use DuckDB for local state")
        d = diff_snapshot(snap, self.s.snapshot())
        self.assertFalse(d["fresh"])
        self.assertTrue(d['compact'])
        fresh = build_brief(self.s, "task", budget_chars=8000)
        self.assertIn("DuckDB", fresh["text"])
        self.assertNotIn("Use SQLite for local state", fresh["text"])


class BriefPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.s = Store(os.path.join(self.tmp, "ctx.sqlite"))

    def tearDown(self):
        self.s.close()

    def test_omitted_collapses_past_threshold(self):
        for i in range(60):
            self.s.add("note", f"filler record number {i} with several extra words")
        r = build_brief(self.s, "nothing in particular", budget_chars=200)
        self.assertGreater(len(r["omitted"]), 25)
        self.assertIn("## Omitted (", r["text"])
        self.assertIn("× note", r["text"])
        self.assertIn("--full-omitted", r["text"])
        # the full list is available on request
        full = build_brief(self.s, "nothing in particular", budget_chars=200, full_omitted=True)
        self.assertIn("## Omitted (did not fit)", full["text"])

    def test_reserved_share_leaves_room_for_task_records(self):
        for _ in range(6):
            self.s.add("constraint", "constraint alpha rule here")
        self.s.add("note", "note about target widget")
        tight = build_brief(self.s, "note target widget", budget_chars=100, reserved_share=1.0)
        fair = build_brief(self.s, "note target widget", budget_chars=100, reserved_share=0.5)
        # with all the budget reserved for constraints, the task match is crowded out
        self.assertNotIn("note about target widget", tight["text"])
        # with a fair share, the task-relevant note survives
        self.assertIn("note about target widget", fair["text"])
        self.assertGreaterEqual(fair["coverage"]["reserved_omitted"], 1)


if __name__ == "__main__":
    unittest.main()
