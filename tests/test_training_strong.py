import tempfile
import unittest
from pathlib import Path

import duckdb

from light_labs.training import strong

FIXTURE = Path(__file__).resolve().parents[1] / "analytics/fixtures/strong/strong-2026-11-01.csv"


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.sets = strong.parse(FIXTURE.read_bytes())

    def test_rest_timers_are_dropped(self):
        self.assertEqual(len(self.sets), 15)
        self.assertNotIn(120.0, {s["seconds"] for s in self.sets})

    def test_letter_set_order_is_a_type_numbered_by_position(self):
        bench = [s for s in self.sets if s["exercise"] == "Bench Press (Dumbbell)"]
        self.assertEqual(
            [(s["set_number"], s["set_type"]) for s in bench],
            [(1, "normal"), (2, "failure"), (3, "normal")],
        )

    def test_set_ids_are_unique_and_stable(self):
        ids = [s["set_id"] for s in self.sets]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(ids, [s["set_id"] for s in strong.parse(FIXTURE.read_text())])

    def test_duration_and_units(self):
        self.assertEqual({s["duration_minutes"] for s in self.sets}, {48, 65, 44})
        self.assertEqual({s["unit"] for s in self.sets}, {"lb"})
        self.assertIsNone(self.sets[0]["rpe"])
        self.assertIsNone(self.sets[0]["notes"])

    def test_bom_is_accepted(self):
        self.assertEqual(len(strong.parse(b"\xef\xbb\xbf" + FIXTURE.read_bytes())), 15)

    def test_unknown_layouts_are_refused(self):
        text = FIXTURE.read_text()
        header, rest = text.split("\n", 1)
        cases = {
            "header differs": header + ",Extra\n" + rest,
            "unknown Set Order": text.replace(",F,", ",X,"),
            "unreadable Duration": text.replace("1h 5m", "about an hour"),
            "fields": text + "2026-10-28 06:00:00,short row\n",
        }
        for message, bad in cases.items():
            with self.subTest(message), self.assertRaisesRegex(strong.NotStrong, message):
                strong.parse(bad)

    def test_summary(self):
        self.assertEqual(strong.summary(self.sets), "15 sets, 2026-10-20 to 2026-10-27")


class IngestTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.var = Path(tmp.name)
        self.db = self.var / "lab.duckdb"

    def drop(self, name, data):
        strong.inbox(self.var).mkdir(parents=True, exist_ok=True)
        (strong.inbox(self.var) / name).write_bytes(data)

    def count(self):
        with duckdb.connect(str(self.db), read_only=True) as con:
            return con.execute("SELECT count(*), max(exported_on) FROM raw.strong_sets").fetchone()

    def test_newest_drop_replaces_the_snapshot_and_the_inbox_empties(self):
        data = FIXTURE.read_bytes()
        self.drop("strong-2026-11-01.csv", data)
        self.drop("strong-2026-11-08.csv", data + data.splitlines(keepends=True)[1])
        path, n = strong.ingest(var=self.var, db=self.db)
        self.assertEqual(path.name, "strong-2026-11-08.csv")
        self.assertEqual(n, 16)
        self.assertEqual(list(strong.inbox(self.var).iterdir()), [])
        self.assertEqual(self.count()[0], 16)
        # Nothing new: the same snapshot reloads.
        self.assertEqual(strong.ingest(var=self.var, db=self.db), (path, 16))

    def test_no_export_yet_leaves_an_empty_table(self):
        self.assertEqual(strong.ingest(var=self.var, db=self.db), (None, 0))
        self.assertEqual(self.count()[0], 0)

    def test_explicit_path_is_copied_in(self):
        path, n = strong.ingest(FIXTURE, var=self.var, db=self.db)
        self.assertEqual((path.parent, n), (strong.home(self.var), 15))
        self.assertEqual(str(self.count()[1]), "2026-11-01")
        self.assertTrue(FIXTURE.exists())


if __name__ == "__main__":
    unittest.main()
