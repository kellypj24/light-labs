import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb

from light_labs.training import stats
from light_labs.training.app import App

MARTS = """
CREATE SCHEMA marts; CREATE SCHEMA intermediate;
CREATE TABLE marts.mart_training_weekly AS SELECT * FROM (VALUES
    (DATE '2026-11-16', '2026-W47', 89.0, 1.42),
    (DATE '2026-11-09', '2026-W46', 77.0, 0.69),
    (DATE '2026-11-02', '2026-W45', 0.0, NULL)
) t(week_start, iso_week, training_minutes, acute_chronic_ratio);
CREATE TABLE marts.mart_training_adherence AS SELECT * FROM (VALUES
    (DATE '2026-11-16', 6, 6, 3, 1, 2, 1, 0.5),
    (DATE '2026-11-09', 2, 2, 2, 0, 0, 0, 1.0)
) t(week_start, planned_sessions, due_sessions, completed_sessions, missed_sick_or_away,
    checked_sessions, checked_only_sessions, adherence_rate);
CREATE TABLE marts.mart_workouts_usage AS SELECT * FROM (VALUES
    (DATE '2026-11-16', 3, 0.47, 0.78), (DATE '2026-11-09', 0, NULL, NULL)
) t(week_start, days_used, checked_share, in_slot_share);
CREATE TABLE marts.mart_lift_progress AS SELECT * FROM (VALUES
    ('Bench <Press>', FALSE, DATE '2026-11-19', 55.0, 5.0, 64.2, 2.5, TRUE),
    ('Pull Up', TRUE, DATE '2026-11-18', 0.0, 4.0, NULL, NULL, TRUE),
    ('Old Lift', FALSE, DATE '2026-10-01', 10.0, 5.0, 12.0, -1.0, FALSE)
) t(exercise, is_bodyweight_lift, last_session_date, top_set_weight, top_set_reps,
    best_e1rm, e1rm_change, is_latest_week);
CREATE TABLE intermediate.int_training_checked_items AS SELECT * FROM (VALUES
    ('a', DATE '2026-11-20', 'Bag 4 x 3 min', FALSE, TRUE),
    ('b', DATE '2026-11-20', 'Bench', TRUE, TRUE),
    ('c', DATE '2026-11-19', 'Cool-down', FALSE, FALSE)
) t(plan_item_id, plan_date, label, is_lift, is_checked);
"""


class StatsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "lab.duckdb"

    def build(self, sql=MARTS):
        with duckdb.connect(str(self.db)) as con:
            con.execute(sql)

    def test_the_report_reads_the_marts_newest_week_first(self):
        self.build()
        rep = stats.report(self.db)
        self.assertEqual(
            [w["iso_week"] for w in rep["weeks"]], ["2026-W47", "2026-W46", "2026-W45"]
        )
        self.assertEqual([x["exercise"] for x in rep["lifts"]], ["Bench <Press>", "Pull Up"])
        self.assertEqual(
            rep["only_here"], [{"plan_date": date(2026, 11, 20), "label": "Bag 4 x 3 min"}]
        )

    def test_the_page_shows_logged_sessions_with_ticks_beside_them(self):
        self.build()
        body = stats.render(stats.report(self.db))
        self.assertIn("<b>3 / 6</b><span>sessions logged</span>", body)
        self.assertIn("<b>2</b><span>ticked here</span>", body)
        self.assertIn('<b class="warn">1.42</b>', body)  # over the deload line
        self.assertIn(
            "89 min · 1 missed sick or away · ticked 47%, 78% in the slot · 1 ticked only", body
        )
        self.assertIn("<span>2/2</span>", body)
        self.assertIn("<span>no plan</span>", body)  # W45: trained before the plans began
        self.assertIn("Bench &lt;Press&gt;", body)
        self.assertIn('55 lb × 5 · e1RM 64<span class="up"> (+2.5)</span> · Nov 19', body)
        self.assertIn("bodyweight × 4 · Nov 18", body)
        self.assertIn("Bag 4 x 3 min", body)
        self.assertNotIn("Cool-down", body)
        self.assertNotIn("Old Lift", body)

    def test_an_empty_or_missing_mart_says_so(self):
        self.build("CREATE SCHEMA marts;")
        with self.assertRaises(stats.Unavailable) as e:
            stats.report(self.db)
        self.assertIn("just analytics", str(e.exception))
        app = App(allowed=["pj@example.com"])
        app.db = self.db
        self.assertIn("no training marts yet", app.stats_page())
        self.assertIn("Nothing logged yet.", stats.render({"weeks": []}))


if __name__ == "__main__":
    unittest.main()
