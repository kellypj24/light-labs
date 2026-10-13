"""Orchestration (light_labs/orchestration): definition invariants, sensor logic, and one full
run over the CI fixtures. Needs the orchestration dependency group; `just dagster-check` runs it."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
ANALYTICS = REPO / "analytics"
HAS_DAGSTER = importlib.util.find_spec("dagster_dbt") is not None


def setUpModule():
    if HAS_DAGSTER and not (ANALYTICS / "target" / "manifest.json").exists():
        subprocess.run(
            ["dbt", "parse", "--quiet", "--profiles-dir", "."], cwd=ANALYTICS, check=True
        )


def fixture_var(root):
    """The CI fixtures laid out like var/: evals/ and rush/queue/."""
    evals = Path(root) / "evals"
    evals.mkdir()
    for path in ANALYTICS.glob("fixtures/*.json*"):
        shutil.copy(path, evals)
    shutil.copytree(ANALYTICS / "fixtures/queue/rush", Path(root) / "rush")
    return Path(root)


def record(evals, run_id, status, ended=None):
    body = {"run_id": run_id, "status": status}
    if ended:
        body["ended_at"] = ended.isoformat()
    (evals / f"{run_id}.run.json").write_text(json.dumps(body))


@unittest.skipUnless(HAS_DAGSTER, "needs the orchestration dependency group")
class DefinitionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from light_labs.orchestration import defs

        cls.defs = defs
        cls.graph = defs.resolve_asset_graph()

    def test_sensors_are_on_and_only_launch_landing_and_dbt(self):
        from dagster import DefaultSensorStatus

        for s in self.defs.sensors:
            self.assertEqual(s.default_status, DefaultSensorStatus.RUNNING, s.name)
            for target in s.targets:
                job = self.defs.resolve_job_def(target.job_name)
                groups = {self.graph.get(k).group_name for k in job.asset_layer.selected_asset_keys}
                self.assertLessEqual(groups, {"landing", "staging", "intermediate", "marts"})

    def test_every_dbt_source_is_landed_by_an_asset(self):
        manifest = json.loads((ANALYTICS / "target/manifest.json").read_text())
        landed = {
            k.to_user_string()
            for k in self.graph.get_all_asset_keys()
            if self.graph.get(k).group_name == "landing"
        }
        for source in manifest["sources"].values():
            self.assertIn(f"{source['source_name']}/{source['name']}", landed)

    def test_every_dbt_model_is_an_asset(self):
        manifest = json.loads((ANALYTICS / "target/manifest.json").read_text())
        models = {
            f"{n['config']['schema']}/{n['name']}"
            for n in manifest["nodes"].values()
            if n["resource_type"] == "model"
        }
        keys = {k.to_user_string() for k in self.graph.get_all_asset_keys()}
        self.assertEqual(models - keys, set())

    def test_steps_run_in_one_process(self):
        # DuckDB allows one writer; parallel step processes lock each other out.
        for job in self.defs.resolve_all_job_defs():
            self.assertEqual(job.executor_def.name, "in_process", job.name)

    def test_staging_reads_the_landed_source(self):
        from dagster import AssetKey

        parents = self.graph.get(AssetKey(["staging", "stg_queue_items"])).parent_keys
        self.assertEqual(parents, {AssetKey(["raw", "queue_items"])})


@unittest.skipUnless(HAS_DAGSTER, "needs the orchestration dependency group")
class SensorLogicTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.var = Path(tmp.name)
        self.evals = self.var / "evals"
        self.evals.mkdir()
        self.now = datetime.now(UTC)

    def test_live_fight_needs_a_fresh_running_record(self):
        from light_labs.orchestration.sensors import live_fight

        record(self.evals, "r1", "completed", self.now)
        self.assertIsNone(live_fight(self.evals))
        record(self.evals, "r2", "running")
        self.assertEqual(live_fight(self.evals), "r2")
        # Killed runner: still "running", nothing written for 10 minutes.
        self.assertIsNone(live_fight(self.evals, now=self.now + timedelta(minutes=10)))

    def test_finished_since_waits_to_settle_and_advances_the_cursor(self):
        from light_labs.orchestration.sensors import finished_since

        start = (self.now - timedelta(hours=1)).isoformat()
        record(self.evals, "old", "completed", self.now - timedelta(hours=2))
        record(self.evals, "a", "cancelled", self.now - timedelta(minutes=10))
        record(self.evals, "b", "completed", self.now - timedelta(seconds=30))
        runs, cursor = finished_since(self.evals, start, now=self.now)
        self.assertEqual(runs, ["a"])  # b ended 30s ago: `just eval` may still be loading
        later = self.now + timedelta(minutes=5)
        runs, cursor = finished_since(self.evals, cursor, now=later)
        self.assertEqual(runs, ["b"])
        self.assertEqual(finished_since(self.evals, cursor, now=later), ([], cursor))

    def test_queue_fingerprint_moves_with_the_queue(self):
        from light_labs.orchestration.sensors import queue_fingerprint

        empty = queue_fingerprint(self.var)
        pending = self.var / "rush/queue/pending"
        pending.mkdir(parents=True)
        (pending / "q1.json").write_text("{}")
        added = queue_fingerprint(self.var)
        self.assertNotEqual(added, empty)
        sent = self.var / "rush/queue/sent"
        sent.mkdir()
        (pending / "q1.json").rename(sent / "q1.json")
        self.assertNotIn(queue_fingerprint(self.var), {empty, added})

    def test_sensors_hold_off_during_a_fight(self):
        from dagster import SkipReason, build_sensor_context

        from light_labs.orchestration import sensors

        record(self.evals, "live", "running")
        with mock.patch.object(sensors.config, "VAR", self.var):
            for s in (sensors.fight_finished, sensors.queue_changed):
                result = s(build_sensor_context(cursor="2026-01-01T00:00:00+00:00"))
                self.assertIsInstance(result, SkipReason)
                self.assertIn("live is running", result.skip_message)

    def test_fight_finished_starts_from_now_then_requests_one_run(self):
        from dagster import RunRequest, SkipReason, build_sensor_context

        from light_labs.orchestration import sensors

        record(self.evals, "old", "completed", self.now - timedelta(days=1))
        with mock.patch.object(sensors.config, "VAR", self.var):
            context = build_sensor_context()
            self.assertIsInstance(sensors.fight_finished(context), SkipReason)
            record(self.evals, "new", "completed", datetime.now(UTC))
            with mock.patch.object(sensors, "SETTLE", timedelta(0)):
                request = sensors.fight_finished(build_sensor_context(cursor=context.cursor))
        self.assertIsInstance(request, RunRequest)
        self.assertEqual(request.tags["lab/runs"], "new")


@unittest.skipUnless(HAS_DAGSTER, "needs the orchestration dependency group")
class FullRunTest(unittest.TestCase):
    def test_analytics_job_over_the_ci_fixtures(self):
        with tempfile.TemporaryDirectory() as tmp:
            var = fixture_var(tmp)
            env = {**os.environ, "LAB_VAR": str(var), "DUCKDB_PATH": str(var / "lab.duckdb")}
            script = (
                "from light_labs.orchestration import defs\n"
                "r = defs.resolve_job_def('analytics_job').execute_in_process()\n"
                "raise SystemExit(0 if r.success else 1)\n"
            )
            done = subprocess.run(
                [sys.executable, "-c", script],
                cwd=REPO,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-3000:])
            import duckdb

            with duckdb.connect(str(var / "lab.duckdb"), read_only=True) as con:
                for table in ("mart_weapon_status", "mart_queue_daily", "mart_run_health"):
                    n = con.execute(f"SELECT count(*) FROM marts.{table}").fetchone()[0]
                    self.assertGreater(n, 0, table)


if __name__ == "__main__":
    unittest.main()
