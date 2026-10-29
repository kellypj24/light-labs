import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from light_labs.core import heavy

COOL = {"thermal": "nominal", "battery_c": 33.0, "speed_limit": 100, "load_1": 2.0, "cores": 10,
        "pressure": "normal", "swap_mb": 100.0}  # fmt: skip


def at(**kw):
    return {**COOL, **kw}


class ReadingsTest(unittest.TestCase):
    def test_too_busy(self):
        self.assertEqual(heavy.too_busy(COOL, []), "")
        self.assertIn("load 14.0 > 10", heavy.too_busy(at(load_1=14.0), []))
        self.assertIn("memory pressure warn", heavy.too_busy(at(pressure="warn"), []))
        self.assertIn("busy: 7 dbt build", heavy.too_busy(COOL, ["7 dbt build"]))

    def test_no_readings_never_block(self):
        none = dict.fromkeys(COOL)
        self.assertEqual(heavy.too_busy(none, []), "")
        self.assertEqual(heavy.hot(none), "")
        self.assertEqual(heavy.critical(none, None), "")

    def test_hot_pauses_on_heat_throttle_and_warn_pressure(self):
        self.assertEqual(heavy.hot(COOL), "")
        self.assertIn("41.5°C", heavy.hot(at(battery_c=41.5)))
        self.assertIn("throttled to 80%", heavy.hot(at(speed_limit=80)))
        self.assertEqual(heavy.hot(at(pressure="warn")), "memory pressure warn")

    def test_thermal_state(self):
        self.assertEqual(heavy.hot(at(thermal="fair")), "")
        self.assertEqual(heavy.hot(at(thermal="serious")), "thermal state serious")
        self.assertEqual(heavy.critical(at(thermal="critical"), 100.0), "thermal state critical")
        self.assertIn("thermal state serious", heavy.too_busy(at(thermal="serious"), []))

    def test_critical_stops_on_pressure_and_swap_growth(self):
        self.assertEqual(heavy.critical(at(swap_mb=2000.0), 100.0), "")
        self.assertEqual(heavy.critical(at(pressure="critical"), 100.0), "memory pressure critical")
        self.assertIn("swap grew 3000 MB", heavy.critical(at(swap_mb=3100.0), 100.0))

    def test_busy_processes_match_vms_and_dagster_runs(self):
        ps = ("  1 /sbin/launchd\n"
              "  2 .../com.apple.Virtualization.VirtualMachine.xpc/Contents/MacOS/x\n"
              "  3 python -m dagster api execute_run {...}\n"
              "  4 python -m dagster api grpc --lazy-load-user-code\n")  # fmt: skip
        self.assertEqual([p.split()[0] for p in heavy.busy_processes(ps)], ["2", "3"])


class LockTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lock = Path(tmp.name) / "heavy.lock"

    def test_one_holder_at_a_time(self):
        heavy.acquire("fight", self.lock)
        self.assertEqual(heavy.holder(self.lock)["job"], "fight")
        with self.assertRaisesRegex(heavy.Busy, "fight"):
            heavy.acquire("roll-keep", self.lock)
        heavy.release(self.lock)
        self.assertIsNone(heavy.holder(self.lock))

    def test_a_dead_holder_is_stale(self):
        self.lock.write_text(json.dumps({"job": "fight", "pid": 2**22 + 1, "started_at": "x"}))
        self.assertEqual(heavy.acquire("check", self.lock)["job"], "check")


class GuardTest(unittest.TestCase):
    def test_pauses_until_cool(self):
        temps = iter([45.0, 42.0, 35.0])
        slept = []
        guard = heavy.Guard(read=lambda: at(battery_c=next(temps)), sleep=slept.append,
                            max_wait=600, step=30)  # fmt: skip
        guard.check()
        self.assertEqual((slept, guard.paused_s), ([30, 30], 60))

    def test_stops_when_still_hot_at_max_wait(self):
        guard = heavy.Guard(read=lambda: at(battery_c=45.0), sleep=lambda s: None,
                            max_wait=60, step=30)  # fmt: skip
        with self.assertRaisesRegex(heavy.Overheated, "45.0°C > 40°C for 1 min"):
            guard.check()

    def test_a_watchdog_stop_raises_on_the_next_check(self):
        guard = heavy.Guard(read=lambda: COOL)
        guard.stop_reason = "memory pressure critical"
        with self.assertRaisesRegex(heavy.Overheated, "critical"):
            guard.check()


@mock.patch.dict(os.environ, {"CI": ""})
class JobTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lock = Path(tmp.name) / "heavy.lock"
        patcher = mock.patch.object(heavy, "busy_processes", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_refuses_a_busy_machine_unless_forced(self):
        busy = heavy.job("fight", read=lambda: at(load_1=14.0), lock=self.lock)
        with self.assertRaisesRegex(heavy.Busy, "load 14.0"), busy:
            pass
        self.assertIsNone(heavy.holder(self.lock))
        with heavy.job("fight", force="PJ said so", read=lambda: at(load_1=14.0), lock=self.lock):
            self.assertEqual(heavy.holder(self.lock)["job"], "fight")
        self.assertIsNone(heavy.holder(self.lock))

    def test_watchdog_stops_on_critical_and_models_unload(self):
        reads = []

        def read():
            reads.append(1)
            return COOL if len(reads) == 1 else at(pressure="critical")

        stopped = []
        job = heavy.job("roll-keep", read=read, lock=self.lock, on_stop=stopped.append, every=0.01)
        with (
            mock.patch.object(heavy, "unload_models") as unload,
            self.assertRaises(heavy.Overheated),
            job as guard,
        ):
            for _ in range(500):
                guard.check()
                heavy.time.sleep(0.01)
        self.assertEqual(stopped, ["memory pressure critical"])
        unload.assert_called_once()
        self.assertIsNone(heavy.holder(self.lock))

    def test_ci_skips_the_lock(self):
        with (
            mock.patch.dict(os.environ, {"CI": "true"}),
            heavy.job("check", read=lambda: at(load_1=99.0), lock=self.lock),
        ):
            self.assertIsNone(heavy.holder(self.lock))
