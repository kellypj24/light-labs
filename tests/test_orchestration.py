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
    # `just check` holds the real heavy-job lock while these run; the sensors must not see it.
    from light_labs.core import heavy

    lock = mock.patch.object(heavy, "LOCK", Path(tempfile.mkdtemp()) / "heavy.lock")
    lock.start()
    unittest.addModuleCleanup(lock.stop)
    if HAS_DAGSTER and not (ANALYTICS / "target" / "manifest.json").exists():
        subprocess.run(
            ["dbt", "parse", "--quiet", "--profiles-dir", "."], cwd=ANALYTICS, check=True
        )


def fixture_var(root):
    """The CI fixtures laid out like var/: evals/, rush/queue/, roll/pairs/, the Claude
    Code transcripts as the archive copy in claude/projects/, and Strong and Health drops
    in training/<kind>/inbox/."""
    evals = Path(root) / "evals"
    evals.mkdir()
    for path in ANALYTICS.glob("fixtures/*.json*"):
        shutil.copy(path, evals)
    shutil.copytree(ANALYTICS / "fixtures/queue/rush", Path(root) / "rush")
    shutil.copytree(ANALYTICS / "fixtures/claude/projects", Path(root) / "claude/projects")
    shutil.copytree(ANALYTICS / "fixtures/calibration/roll", Path(root) / "roll")
    shutil.copytree(ANALYTICS / "fixtures/strong", Path(root) / "training/strong/inbox")
    shutil.copytree(ANALYTICS / "fixtures/health", Path(root) / "training/health/inbox")
    shutil.copytree(ANALYTICS / "fixtures/training/plans", Path(root) / "training/plans")
    (Path(root) / "training/notes").mkdir()
    shutil.copy(ANALYTICS / "fixtures/training/notes.jsonl", Path(root) / "training/notes")
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
        parents = self.graph.get(AssetKey(["staging", "stg_strong_sets"])).parent_keys
        self.assertEqual(parents, {AssetKey(["raw", "strong_sets"])})
        parents = self.graph.get(AssetKey(["staging", "stg_health_workouts"])).parent_keys
        self.assertEqual(parents, {AssetKey(["raw", "health_workouts"])})


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

    def test_record_fingerprint_waits_for_notes_and_plans_to_settle(self):
        from light_labs.orchestration.sensors import record_fingerprint

        self.assertIsNone(record_fingerprint(self.var))
        notes = self.var / "training/notes/notes.jsonl"
        notes.parent.mkdir(parents=True)
        notes.write_text("{}\n")
        wrote = datetime.fromtimestamp(notes.stat().st_mtime, UTC)
        self.assertIsNone(record_fingerprint(self.var, now=wrote + timedelta(seconds=30)))
        settled = record_fingerprint(self.var, now=wrote + timedelta(minutes=3))
        self.assertIsNotNone(settled)
        plan = self.var / "training/plans/2026-W47.json"
        plan.parent.mkdir()
        plan.write_text("{}")
        os.utime(plan, (wrote.timestamp() + 1, wrote.timestamp() + 1))
        later = record_fingerprint(self.var, now=wrote + timedelta(minutes=5))
        self.assertNotIn(later, {None, settled})

    def test_sensors_hold_off_during_a_fight(self):
        from dagster import SkipReason, build_sensor_context

        from light_labs.orchestration import sensors

        record(self.evals, "live", "running")
        with mock.patch.object(sensors.config, "VAR", self.var):
            for s in sensors.ALL_SENSORS:
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

    def test_drop_fingerprint_is_none_until_a_drop_and_moves_with_it(self):
        from light_labs.orchestration.sensors import drop_fingerprint

        self.assertIsNone(drop_fingerprint(self.var))
        box = self.var / "training/strong/inbox"
        box.mkdir(parents=True)
        self.assertIsNone(drop_fingerprint(self.var))
        (box / "strong-2026-11-08.csv").write_text("a")
        first = drop_fingerprint(self.var)
        self.assertIsNotNone(first)
        (box / "strong-2026-11-08.csv").write_text("ab")  # same-day resend replaces it
        self.assertNotEqual(drop_fingerprint(self.var), first)

    def test_drop_fingerprints_are_per_kind(self):
        from light_labs.orchestration.sensors import drop_fingerprint

        box = self.var / "training/health/inbox"
        box.mkdir(parents=True)
        (box / "health-2026-11-09-194822.json").write_text("{}")
        self.assertIsNotNone(drop_fingerprint(self.var, "health"))
        self.assertIsNone(drop_fingerprint(self.var, "strong"))

    def test_strong_dropped_requests_once_per_drop(self):
        from dagster import RunRequest, SkipReason, build_sensor_context

        from light_labs.orchestration import sensors

        with mock.patch.object(sensors.config, "VAR", self.var):
            self.assertIsInstance(sensors.strong_dropped(build_sensor_context()), SkipReason)
            box = self.var / "training/strong/inbox"
            box.mkdir(parents=True)
            (box / "strong-2026-11-08.csv").write_text("a")
            context = build_sensor_context()
            self.assertIsInstance(sensors.strong_dropped(context), RunRequest)
            again = sensors.strong_dropped(build_sensor_context(cursor=context.cursor))
            self.assertIsInstance(again, SkipReason)

    def test_claude_daily_runs_once_per_utc_day(self):
        from light_labs.orchestration.sensors import claude_due

        now = datetime(2026, 10, 19, 23, 30, tzinfo=UTC)
        self.assertEqual(claude_due("2026-10-18", now), "2026-10-19")
        self.assertIsNone(claude_due("2026-10-19", now))
        self.assertEqual(claude_due("2026-10-19", now + timedelta(hours=1)), "2026-10-20")


@unittest.skipUnless(HAS_DAGSTER, "needs the orchestration dependency group")
class FullRunTest(unittest.TestCase):
    def test_analytics_job_over_the_ci_fixtures(self):
        with tempfile.TemporaryDirectory() as tmp:
            var = fixture_var(tmp)
            env = {
                **os.environ,
                "LAB_VAR": str(var),
                "DUCKDB_PATH": str(var / "lab.duckdb"),
                # Never the real ~/.claude: transcripts come from the archive copy only.
                "LAB_CLAUDE_PROJECTS": str(var / "no-live-transcripts"),
            }
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
                for table in (
                    "mart_weapon_status",
                    "mart_queue_daily",
                    "mart_run_health",
                    "mart_claude_sessions",
                    "mart_claude_repeated_work",
                    "mart_claude_activity_weekly",
                    "mart_calibration",
                    "mart_training_weekly",
                    "mart_training_weekly_breakdown",
                    "mart_lift_progress",
                    "mart_training_adherence",
                ):
                    n = con.execute(f"SELECT count(*) FROM marts.{table}").fetchone()[0]
                    self.assertGreater(n, 0, table)
                # W44: five sessions planned; the lift on the 29th was missed, a sick day.
                week = con.execute(
                    "SELECT planned_sessions, completed_sessions, missed_sessions, "
                    "missed_sick_or_away, sick_days, away_days, adherence_rate "
                    "FROM marts.mart_training_adherence WHERE iso_week = '2026-W44'"
                ).fetchone()
                self.assertEqual(week, (5, 4, 1, 1, 1, 0, 0.8))  # the voided trip isn't counted
                chores = con.execute(
                    "SELECT chore_minutes FROM marts.mart_training_weekly "
                    "WHERE iso_week = '2026-W43'"
                ).fetchone()
                self.assertEqual(chores, (90,))
                n = con.execute("SELECT count(*) FROM staging.stg_strong_sets").fetchone()[0]
                self.assertEqual(n, 15)
                flags = con.execute(
                    "SELECT right(workout_uuid, 1), is_fragment, is_duplicate, "
                    "is_implausible_pace, is_counted FROM staging.stg_health_workouts "
                    "ORDER BY 1"
                ).fetchall()
                self.assertEqual(
                    flags,
                    [
                        ("1", False, False, False, True),
                        ("2", True, False, False, False),  # 70 s accidental start
                        ("3", False, False, False, True),  # has heart rate: kept
                        ("4", False, True, True, False),  # same run, 23 h long
                        ("5", False, False, False, True),  # indoor ride
                        ("6", False, False, False, True),  # from the second drop
                    ],
                )
            self.assertEqual(list((var / "training/strong/inbox").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
