import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from light_labs.training import record

FIXTURES = Path(__file__).resolve().parents[1] / "analytics/fixtures/training"


class RecordTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.var = Path(tmp.name)
        self.db = self.var / "lab.duckdb"

    def rows(self, sql):
        with duckdb.connect(str(self.db), read_only=True) as con:
            return con.execute(sql).fetchall()

    def test_notes_land_one_row_per_thing_with_voided_ones_flagged(self):
        self.assertEqual(record.ingest_notes(FIXTURES / "notes.jsonl", db=self.db), 5)
        got = self.rows(
            "SELECT note_id, row_index, kind, is_voided, wants_replan "
            "FROM raw.training_notes ORDER BY 1, 2"
        )
        self.assertEqual(
            got,
            [
                ("n1", 0, "chore", False, False),
                ("n2", 0, "event", False, True),
                ("n2", 1, "sick", False, True),
                ("n3", 0, "travel", True, False),  # /note undo
                ("n4", 0, "ache", False, False),  # saved in work hours, read later
            ],
        )

    def test_a_reload_replaces_and_no_file_is_an_empty_table(self):
        record.ingest_notes(FIXTURES / "notes.jsonl", db=self.db)
        self.assertEqual(record.ingest_notes(var=self.var, db=self.db), 0)
        self.assertEqual(self.rows("SELECT count(*) FROM raw.training_notes"), [(0,)])
        self.assertEqual(record.ingest_plans(var=self.var, db=self.db), (0, 0))

    def test_plans_land_one_row_per_day(self):
        plans = self.var / "training" / "plans"
        plans.mkdir(parents=True)
        (plans / "2026-W44.json").write_text((FIXTURES / "plans/2026-W44.json").read_text())
        (plans / "2026-W44.md").write_text("# not a plan file the loader reads")
        self.assertEqual(record.ingest_plans(var=self.var, db=self.db), (1, 7))
        got = self.rows(
            "SELECT plan_date::VARCHAR, iso_week, is_rest, slot_start, session_type, item_count "
            "FROM raw.training_plan_days ORDER BY 1"
        )
        self.assertEqual(got[0], ("2026-10-26", "2026-W44", False, "15:00", "run", 3))
        self.assertEqual(got[-1], ("2026-11-01", "2026-W44", True, None, None, 0))

    def test_a_replanned_week_replaces_its_days(self):
        plans = self.var / "training" / "plans"
        plans.mkdir(parents=True)
        plan = json.loads((FIXTURES / "plans/2026-W44.json").read_text())
        (plans / "2026-W44.json").write_text(json.dumps(plan))
        record.ingest_plans(var=self.var, db=self.db)
        plan["days"][0] = {"date": "2026-10-26", "rest": True, "slot": None, "items": []}
        (plans / "2026-W44.json").write_text(json.dumps(plan))
        self.assertEqual(record.ingest_plans(var=self.var, db=self.db), (1, 7))
        self.assertEqual(
            self.rows("SELECT is_rest FROM raw.training_plan_days WHERE plan_date = '2026-10-26'"),
            [(True,)],
        )


if __name__ == "__main__":
    unittest.main()
