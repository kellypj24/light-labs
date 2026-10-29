import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from light_labs.core import heavy, monitor

COOL = {
    "thermal": "nominal",
    "battery_c": None,
    "speed_limit": 100,
    "load_1": 2.0,
    "cores": 10,
    "pressure": "normal",
    "swap_mb": 1500.0,
}
MAIL_SUBJECT = "Subject: your tax return"


@mock.patch.dict(os.environ, {"CI": ""})
class SnapshotTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.lock = self.root / "heavy.lock"
        self.var = self.root / "var"
        (self.var / "roll" / "keep").mkdir(parents=True)

    def hold(self, job, **detail):
        heavy.acquire(job, self.lock, var=str(self.var), swap_start=1000.0, detail=detail)
        self.addCleanup(heavy.release, self.lock)

    def snap(self, procs=()):
        return monitor.snapshot(
            lock=self.lock, read=lambda: COOL, procs=list(procs), db=self.root / "none.db"
        )

    def test_shadow_progress_counts_records_without_reading_them(self):
        self.hold("roll-keep", label="Roll/Social", sample=200, cmd="lab x --token abc")
        rec = json.dumps({"subject": MAIL_SUBJECT, "from": "irs@example.com"})
        (self.var / "roll" / "keep" / "shadow-20990101T000000Z.jsonl").write_text((rec + "\n") * 3)
        snap = self.snap(procs=["4242 /usr/bin/qemu-system-aarch64 -drive token=abc"])
        job = snap["job"]
        self.assertEqual(job["progress"], {"what": "Roll/Social", "done": 3, "total": 200})
        self.assertEqual(job["detail"], {"label": "Roll/Social", "sample": 200})
        self.assertEqual(job["swap_growth_mb"], 500.0)
        self.assertEqual(snap["busy"], ["container VM"])
        self.assertEqual(snap["why_not"], "roll-keep holds the lock")
        out = json.dumps(snap)
        for leak in ("tax return", "irs@", "token", str(self.var), str(os.getpid())):
            self.assertNotIn(leak, out)

    def test_fight_progress_from_its_run_record(self):
        self.hold("fight")
        (self.var / "evals").mkdir()
        (self.var / "evals" / "mail-keep-x.run.json").write_text(
            json.dumps({"run_id": "mail-keep-x", "done": 7, "total": 40, "status": "running"})
        )
        self.assertEqual(
            self.snap()["job"]["progress"], {"what": "mail-keep-x", "done": 7, "total": 40}
        )

    def test_history_keeps_only_public_fields(self):
        with (
            mock.patch.object(heavy, "busy_processes", return_value=[]),
            heavy.job("check", read=lambda: COOL, lock=self.lock, detail={"cmd": "x"}),
        ):
            pass
        (h,) = self.snap()["history"]
        self.assertEqual(set(h), set(monitor.HISTORY_KEYS))
        self.assertEqual((h["job"], h["outcome"]), ("check", "done"))
        self.assertIsNone(self.snap()["job"])
        self.assertTrue(self.snap()["start_ok"])

    def test_dagster_lists_active_runs_first(self):
        db = self.root / "runs.db"
        with sqlite3.connect(db) as con:
            con.execute(
                "CREATE TABLE runs (id INTEGER PRIMARY KEY, pipeline_name TEXT, "
                "status TEXT, start_time FLOAT, end_time FLOAT)"
            )
            con.execute("INSERT INTO runs VALUES (1, 'analytics_job', 'STARTED', 1.0, NULL)")
            con.execute("INSERT INTO runs VALUES (2, 'queue_job', 'SUCCESS', 2.0, 3.0)")
        runs = monitor.dagster_runs(db)
        self.assertEqual(
            [(r["job"], r["active"]) for r in runs], [("analytics_job", True), ("queue_job", False)]
        )
        self.assertEqual(monitor.dagster_runs(self.root / "missing.db"), [])
