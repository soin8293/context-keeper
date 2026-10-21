"""Requirement coverage named in PRD §4–§5.

I3 determinism · FR4 search/status · FR6 install.
"""
import contextlib
import io
import pathlib
import tempfile
import unittest

from contextkeeper import cli
from contextkeeper.brief import build_brief
from contextkeeper.ingest import ingest
from contextkeeper.store import Store

import install  # repo-root module


class DeterminismTests(unittest.TestCase):
    """I3 — same inputs produce the same records and the same brief."""

    def test_ingest_is_deterministic(self):
        def run_once():
            tmp = pathlib.Path(tempfile.mkdtemp())
            root = tmp / "p"
            root.mkdir()
            (root / "AGENTS.md").write_text(
                "# P\n\n## Constraints\n- Never send raw data out to anyone\n\n"
                "## Decisions\n- We use SQLite for local state\n",
                encoding="utf-8",
            )
            s = Store(str(tmp / "c.sqlite"))
            ingest(s, root)
            rows = [(r["kind"], r["text"], r["scope"]) for r in s.current()]
            s.close()
            return rows

        self.assertEqual(run_once(), run_once())

    def test_brief_is_deterministic(self):
        def build_once():
            tmp = pathlib.Path(tempfile.mkdtemp())
            s = Store(str(tmp / "c.sqlite"))
            s.add("constraint", "Never send raw data out")
            s.add("decision", "We use SQLite for local state", scope="api")
            s.add("fact", "The importer handles zip files")
            s.add("note", "filler " + "x" * 100)
            text = build_brief(s, "work on the importer", budget_chars=200)["text"]
            s.close()
            # the timestamp is the only intentionally non-deterministic line
            return "\n".join(
                line for line in text.splitlines() if not line.startswith("- **Generated:**")
            )

        self.assertEqual(build_once(), build_once())


class CliQueryTests(unittest.TestCase):
    """FR4 — search and status report the current view only."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.db = str(self.tmp / "c.sqlite")
        s = Store(self.db)
        s.add("decision", "Use SQLite for local state", scope="api")
        s.add("constraint", "Never send raw archive data to a provider")
        s.add("state", "Importer rewrite is on hold")
        s.close()

    def _run(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["--db", self.db, *args])
        return rc, buf.getvalue()

    def test_search_returns_matches_and_hides_non_matches(self):
        rc, out = self._run("search", "sqlite")
        self.assertEqual(rc, 0)
        self.assertIn("Use SQLite for local state", out)
        self.assertNotIn("provider", out)

    def test_search_reports_no_match(self):
        _, out = self._run("search", "zzzznothing")
        self.assertIn("no current records matched", out)

    def test_search_shows_current_view_after_correction(self):
        s = Store(self.db)
        rid = [r["id"] for r in s.current() if "SQLite" in r["text"]][0]
        s.correct(rid, "Use DuckDB for local state")
        s.close()
        _, out = self._run("search", "sqlite")
        self.assertNotIn("Use SQLite", out)
        _, out = self._run("search", "duckdb")
        self.assertIn("Use DuckDB", out)

    def test_status_counts_current_and_drops_retired(self):
        _, out = self._run("status")
        self.assertIn("current records: 3", out)
        s = Store(self.db)
        rid = [r["id"] for r in s.current() if r["kind"] == "state"][0]
        s.retire(rid)
        s.close()
        _, out = self._run("status")
        self.assertIn("current records: 2", out)

    def test_search_scope_includes_global_and_excludes_other_scopes(self):
        s = Store(self.db)
        s.add("fact", "web only marker", scope="web")
        s.close()
        _, out = self._run("search", "web", "--scope", "api")
        self.assertNotIn("web only marker", out)  # a different scope is excluded
        _, out = self._run("search", "sqlite", "--scope", "api")
        self.assertIn("SQLite", out)  # the api record (and globals) are included


class InstallTests(unittest.TestCase):
    """FR6 — wiring a project yields a working store and day-one context."""

    def _project(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        proj = tmp / "proj"
        proj.mkdir()
        (proj / "AGENTS.md").write_text(
            "# P\n\n## Constraints\n- Never commit secrets to the repository\n",
            encoding="utf-8",
        )
        return proj

    def test_wire_project_creates_store_runner_and_day_one_context(self):
        proj = self._project()
        rc = install.wire_project(proj)
        self.assertEqual(rc, 0)
        store = proj / ".context-keeper" / "context.sqlite"
        self.assertTrue(store.is_file())
        self.assertTrue((proj / ".context-keeper" / "ck.py").is_file())
        agents = (proj / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("<!-- context-keeper:begin -->", agents)
        s = Store(str(store))
        self.assertGreaterEqual(len(s.current()), 1)  # context exists on day one
        s.close()

    def test_wire_project_is_safe_to_rerun_without_duplicating_the_block(self):
        proj = self._project()
        install.wire_project(proj)
        install.wire_project(proj)
        agents = (proj / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(agents.count("<!-- context-keeper:begin -->"), 1)


if __name__ == "__main__":
    unittest.main()
