import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb

from light_labs.core import usage

MARTS = """
CREATE SCHEMA marts;
CREATE TABLE marts.mart_claude_activity_weekly (
    week_start DATE, project VARCHAR, worktree VARCHAR, turn_count BIGINT,
    working_seconds DOUBLE, thinking_seconds DOUBLE, reading_seconds DOUBLE,
    editing_seconds DOUBLE, shell_seconds DOUBLE, web_seconds DOUBLE,
    subagent_seconds DOUBLE, asking_seconds DOUBLE, other_tool_seconds DOUBLE);
CREATE TABLE marts.mart_claude_task_weekly (
    week_start DATE, project VARCHAR, task_type VARCHAR, is_deterministic BOOLEAN,
    call_count BIGINT, error_count BIGINT, total_seconds DOUBLE, context_tokens DOUBLE);
CREATE TABLE marts.mart_claude_repeated_work (
    pattern VARCHAR, task_type VARCHAR, call_count BIGINT, session_count BIGINT,
    project_count BIGINT, total_seconds DOUBLE, context_tokens DOUBLE);
CREATE TABLE marts.mart_claude_sessions (
    started_at TIMESTAMPTZ, ended_at TIMESTAMPTZ, prompt_count BIGINT);
INSERT INTO marts.mart_claude_activity_weekly VALUES
    ('2026-10-12', 'app', 'app', 3, 3600, 1800, 0, 600, 1200, 0, 0, 0, 0),
    ('2026-10-12', 'app', 'app-fix', 1, 1800, 900, 0, 0, 900, 0, 0, 0, 0),
    ('2026-10-05', 'lib', 'lib', 2, 900, 900, 0, 0, 0, 0, 0, 0, 0);
INSERT INTO marts.mart_claude_task_weekly VALUES
    ('2026-10-12', 'app', 'git', TRUE, 10, 1, 60, 3e6),
    ('2026-10-12', 'app', 'edit', FALSE, 5, 0, 30, 1e6);
INSERT INTO marts.mart_claude_repeated_work VALUES
    ('git status', 'git', 10, 2, 1, 60, 3e6), ('python3', 'edit', 5, 1, 1, 30, 1e6);
INSERT INTO marts.mart_claude_sessions VALUES
    ('2026-10-05 09:00:00+00', '2026-10-12 11:00:00+00', 4);
"""


class UsageTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "lab.duckdb"

    def test_page_shows_weeks_projects_and_deterministic_work(self):
        with duckdb.connect(str(self.db)) as con:
            con.execute(MARTS)
        rep = usage.report(self.db)
        self.assertEqual(
            [w["week_start"] for w in rep["weeks"]], [date(2026, 10, 12), date(2026, 10, 5)]
        )
        body = usage.render(rep)
        self.assertIn("1.8h</b> working over 2 weeks", body)
        self.assertIn("1 session · 4 prompts", body)
        self.assertIn("<b>75%</b> of the tokens", body)  # git: 3M of 4M
        self.assertIn("app-fix", body)  # the worktree, folded under app
        self.assertIn("<code>git status</code>", body)
        self.assertNotIn("<code>python3</code>", body)  # not deterministic
        self.assertIn(">1 turn<", body)

    def test_missing_marts_say_how_to_build_them(self):
        duckdb.connect(str(self.db)).close()
        with self.assertRaisesRegex(usage.Unavailable, "just analytics"):
            usage.report(self.db)


if __name__ == "__main__":
    unittest.main()
