import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from light_labs.training import deliver

SUN = datetime(2026, 11, 15)  # a Sunday; next week is 2026-W47


class Phone:
    def __init__(self):
        self.texts = []

    def __call__(self, to, text):
        self.texts.append(text)

    def said(self, needle):
        return any(needle in t for t in self.texts)


class Planner:
    def __init__(self, var, fail=False):
        self.var, self.fail, self.calls = var, fail, []

    def __call__(self, week, from_date=None):
        self.calls.append((week, from_date))
        if self.fail:
            raise RuntimeError("no free windows")
        out = Path(self.var) / "training" / "plans" / f"{week}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# {week}\n\nMon: lift\n\nTue: run\n")
        return out, []


class DeliverTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.var = Path(tmp.name)
        self.phone, self.planner = Phone(), Planner(self.var)

    def drop(self, kind, name, inbox=False):
        folder = self.var / "training" / kind / ("inbox" if inbox else "")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text("x")

    def fresh(self, day=SUN):
        self.drop("strong", f"strong-{day:%Y-%m-%d}.csv")
        self.drop("health", f"health-{day:%Y-%m-%d}-190000.json")

    def tick(self, at):
        return deliver.tick(self.phone, now=at, planner=self.planner, var=self.var)

    def state(self):
        return json.loads((self.var / "training" / "deliver.json").read_text())

    def test_fresh_inputs_plan_once_the_strong_export_lands(self):
        self.fresh()
        self.assertIn("sent 2026-W47", self.tick(SUN.replace(hour=19)))
        self.assertEqual(self.planner.calls, [("2026-W47", None)])
        self.assertTrue(self.phone.said("Next week's plan:"))
        self.assertEqual(self.tick(SUN.replace(hour=20)), [])  # sent once

    def test_nothing_before_six_or_on_other_days(self):
        self.fresh()
        self.assertEqual(self.tick(SUN.replace(hour=17)), [])
        self.assertEqual(self.tick(SUN.replace(hour=19) - timedelta(days=2)), [])

    def test_stale_inputs_are_asked_for_and_the_plan_waits_until_eight(self):
        self.drop("strong", "strong-2026-11-01.csv")  # 14 days old
        self.drop("health", "health-2026-11-12-190000.json")  # 3 days old
        did = self.tick(SUN.replace(hour=18))
        self.assertEqual(did, ["asked for strong", "asked for health"])
        self.assertTrue(self.phone.said("No Strong export since Sun Nov 1"))
        self.assertTrue(self.phone.said("Export Workouts (Last 7 Days)"))
        self.assertEqual(self.planner.calls, [])
        self.assertIn("sent 2026-W47", self.tick(SUN.replace(hour=20)))
        self.assertTrue(self.phone.said("Built without a fresh Strong and Health export"))
        self.assertEqual(self.phone.texts.count(deliver.ASK["strong"].format(since="Sun Nov 1")), 1)

    def test_a_requested_file_refreshes_next_week_once_loaded(self):
        self.drop("strong", "strong-2026-11-01.csv")
        self.drop("health", "health-2026-11-15-190000.json")
        self.tick(SUN.replace(hour=20))  # plans without Strong, asks for it
        self.drop("strong", "strong-2026-11-15.csv", inbox=True)  # sent, not loaded yet
        self.assertEqual(self.tick(SUN.replace(hour=21)), [])
        (self.var / "training/strong/inbox/strong-2026-11-15.csv").rename(
            self.var / "training/strong/strong-2026-11-15.csv"
        )  # Dagster loaded it
        self.assertEqual(self.tick(SUN.replace(hour=22)), ["refreshed after strong"])
        self.assertEqual(self.planner.calls[-1], ("2026-W47", None))
        self.assertTrue(self.phone.said("Updated plan:"))
        self.assertEqual(self.state()["requested"], {})

    def test_midweek_refresh_plans_the_remaining_days(self):
        self.fresh()
        self.tick(SUN.replace(hour=19))  # W47 sent
        wed = SUN + timedelta(days=3, hours=9)  # Wed Nov 18, 09:00
        with deliver._locked(self.var) as state:
            state["requested"]["health"] = (wed - timedelta(hours=1)).isoformat()
        self.drop("health", f"health-{wed:%Y-%m-%d}-085500.json")
        self.assertEqual(self.tick(wed), ["refreshed after health"])
        self.assertEqual(self.planner.calls[-1], ("2026-W47", date(2026, 11, 18)))
        self.assertTrue(self.phone.said("Updated plan for the rest of the week:"))

    def test_health_is_asked_for_nightly_once(self):
        self.fresh(SUN - timedelta(days=3))
        tue = SUN + timedelta(days=2, hours=21)
        self.assertEqual(self.tick(tue), ["asked for health"])
        self.assertEqual(self.tick(tue + timedelta(hours=1)), [])

    def test_planner_errors_are_texted_and_retried(self):
        self.fresh()
        self.planner.fail = True
        self.assertEqual(self.tick(SUN.replace(hour=20)), [])
        self.assertTrue(self.phone.said("Couldn't plan 2026-W47: no free windows"))
        self.planner.fail = False
        self.assertIn("sent 2026-W47", self.tick(SUN.replace(hour=21)))

    def test_long_plans_split_between_days(self):
        text = "\n\n".join(f"Day {i}: " + "x" * 900 for i in range(7))
        parts = deliver.split(text)
        self.assertTrue(all(len(p) <= deliver.TELEGRAM_LIMIT for p in parts))
        self.assertEqual("\n\n".join(parts), text)

    def test_replan_and_send(self):
        self.fresh()
        self.tick(SUN.replace(hour=19))
        deliver.replan(self.phone, now=SUN.replace(hour=22), planner=self.planner, var=self.var)
        self.assertEqual(self.planner.calls[-1], ("2026-W47", None))
        deliver.send_week("2026-W47", self.phone, var=self.var)
        self.assertTrue(self.phone.said("Plan for 2026-W47:"))
        with self.assertRaises(FileNotFoundError):
            deliver.send_week("2026-W50", self.phone, var=self.var)


if __name__ == "__main__":
    unittest.main()
