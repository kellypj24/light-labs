import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from light_labs.training import health

FIXTURES = Path(__file__).resolve().parents[1] / "analytics/fixtures/health"
FIRST = FIXTURES / "health-2026-11-01-210000.json"
SECOND = FIXTURES / "health-2026-11-02-210000.json"


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.exported, self.workouts = health.parse(FIRST.read_bytes())
        self.by_id = {w["workout_uuid"][-1]: w for w in self.workouts}

    def test_export_date_and_count(self):
        self.assertEqual(self.exported.isoformat(), "2026-11-02T02:00:00+00:00")
        self.assertEqual(len(self.workouts), 5)

    def test_columns_from_statistics(self):
        run = self.by_id["3"]
        self.assertEqual((run["distance_m"], run["heart_rate_avg"], run["heart_rate_max"]),
                         (5800.0, 160.0, 178.0))  # fmt: skip
        self.assertEqual(run["event_count"], 2)
        self.assertIsNone(self.by_id["1"]["heart_rate_avg"])
        self.assertIsNone(self.by_id["2"]["distance_m"])

    def test_cycling_distance_in_miles_becomes_metres(self):
        ride = self.by_id["5"]
        self.assertAlmostEqual(ride["distance_m"], 12.5 * 1609.344)
        self.assertTrue(ride["is_indoor"])

    def test_statistics_are_kept_whole(self):
        stats = json.loads(self.by_id["3"]["statistics"])
        self.assertIn("HKQuantityTypeIdentifierHeartRate", stats)

    def test_summary(self):
        self.assertEqual(
            health.summary(self.workouts), "5 workouts (cycling, running), 2026-10-26 to 2026-10-30"
        )

    def test_unknown_shapes_are_refused(self):
        body = json.loads(FIRST.read_text())
        no_uuid = json.loads(FIRST.read_text())
        del no_uuid["workouts"][0]["uuid"]
        furlongs = json.loads(FIRST.read_text())
        stats = furlongs["workouts"][0]["statistics"]
        stats["HKQuantityTypeIdentifierDistanceWalkingRunning"]["unit"] = "furlong"
        cases = {
            "not JSON": "{nope",
            "no `workouts` list": json.dumps({"exportInfo": body["exportInfo"]}),
            "missing \\['uuid'\\]": json.dumps(no_uuid),
            "unknown distance unit": json.dumps(furlongs),
        }
        for message, bad in cases.items():
            with self.subTest(message), self.assertRaisesRegex(health.NotHealth, message):
                health.parse(bad)


class IngestTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.var = Path(tmp.name)
        self.db = self.var / "lab.duckdb"

    def drop(self, path):
        health.inbox(self.var).mkdir(parents=True, exist_ok=True)
        (health.inbox(self.var) / path.name).write_bytes(path.read_bytes())

    def test_drops_upsert_and_the_inbox_empties(self):
        self.drop(FIRST)
        self.assertEqual(health.ingest(var=self.var, db=self.db), (1, 5, 5))
        self.drop(SECOND)
        self.drop(FIRST)  # an overlapping export: same uuids, no duplicates
        self.assertEqual(health.ingest(var=self.var, db=self.db), (2, 6, 6))
        self.assertEqual(list(health.inbox(self.var).iterdir()), [])
        self.assertEqual(len(list(health.home(self.var).glob("*.json"))), 2)

    def test_nothing_dropped_keeps_the_table(self):
        health.ingest([FIRST], var=self.var, db=self.db)
        self.assertEqual(health.ingest(var=self.var, db=self.db), (0, 0, 5))

    def test_empty_start_creates_the_table(self):
        self.assertEqual(health.ingest(var=self.var, db=self.db), (0, 0, 0))
        with duckdb.connect(str(self.db), read_only=True) as con:
            n = con.execute("SELECT count(*) FROM raw.health_workouts").fetchone()[0]
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
