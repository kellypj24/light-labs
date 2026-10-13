import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from light_labs import cli
from light_labs.evals import results, watch

RECORD = {
    "run_id": "s-1",
    "stage": "s",
    "contestants": ["mega-man", "proto"],
    "samples": 1,
    "total": 4,
    "done": 2,
    "passed": 1,
    "harness_errors": 0,
    "cool_pauses": 1,
    "cool_seconds": 30,
    "status": "running",
    "started_at": "2026-10-13T00:00:00Z",
}
SAMPLES = [
    {
        "contestant": "mega-man",
        "fixture": "a",
        "sample": 1,
        "passed": True,
        "checks": [{"name": "ran", "passed": True}],
    },
    {
        "contestant": "mega-man",
        "fixture": "b",
        "sample": 1,
        "passed": False,
        "checks": [{"name": "ran", "passed": True}, {"name": "escalate", "passed": False}],
    },
]
TELEMETRY = [
    {
        "at": "2026-10-13T00:00:00Z",
        "battery_temp_c": 36.0,
        "on_ac": False,
        "battery_pct": 40,
        "cpu_speed_limit": 100,
        "ollama_cpu": 250.0,
    },
    {
        "at": "2026-10-13T00:00:30Z",
        "battery_temp_c": 41.5,
        "on_ac": False,
        "battery_pct": 39,
        "cpu_speed_limit": 80,
        "ollama_cpu": 260.0,
    },
]


class RunHealthTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "s-1.run.json").write_text(json.dumps(RECORD))
        (self.dir / "s-1.jsonl").write_text("".join(json.dumps(s) + "\n" for s in SAMPLES))
        (self.dir / "s-1.telemetry.jsonl").write_text(
            "".join(json.dumps(t) + "\n" for t in TELEMETRY)
        )

    def test_ingest_health_and_samples_skip_telemetry(self):
        db = self.dir / "lab.duckdb"
        self.assertEqual(results.ingest_health(self.dir, db=db), (1, 2))
        with results.connect(db) as con:
            run_id, cool = con.execute(
                "SELECT run_id, cool_pauses FROM raw.eval_run_log"
            ).fetchone()
            ids = con.execute("SELECT DISTINCT run_id FROM raw.eval_telemetry").fetchall()
        self.assertEqual((run_id, cool, ids), ("s-1", 1, [("s-1",)]))
        # telemetry files are not sample files
        with mock.patch.object(results, "RESULTS", self.dir):
            loaded = results.ingest(db=db)
        self.assertNotIn("s-1.telemetry", loaded)

    def test_watch_screen(self):
        now = datetime(2026, 10, 13, 0, 1, 0, tzinfo=UTC)
        screen = watch.render(RECORD, SAMPLES, TELEMETRY, now=now)
        for want in [
            "RUNNING",
            "2/4 samples",
            "1:00 elapsed, ~1:00 left",
            "mega-man     1/2 samples (50%)  1/2 fixtures clean",
            "proto        waiting",
            "mega-man b #1: escalate",
            "battery 41.5°C (peak 41.5)",
            "THROTTLED to 80%",
            "ON BATTERY 39%",
            "cooled 1x",
        ]:
            self.assertIn(want, screen)

    def test_cancel_closes_a_running_record_with_its_reason(self):
        with mock.patch.object(results, "RESULTS", self.dir):
            cli.main(["evals", "cancel", "s-1", "--reason", "machine hot"])
        record = json.loads((self.dir / "s-1.run.json").read_text())
        self.assertEqual((record["status"], record["reason"]), ("cancelled", "machine hot"))
        self.assertIn("ended_at", record)


if __name__ == "__main__":
    unittest.main()
