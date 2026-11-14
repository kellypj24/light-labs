import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

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
        env = mock.patch.dict(os.environ, {"RUSH_REMOTE_URL": ""})  # a developer's .env sets it
        env.start()
        self.addCleanup(env.stop)

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

    def test_a_failed_refresh_is_retried_next_tick(self):
        self.fresh()
        self.tick(SUN.replace(hour=19))  # W47 sent
        wed = SUN + timedelta(days=3, hours=9)
        with deliver._locked(self.var) as state:
            state["requested"]["health"] = (wed - timedelta(hours=1)).isoformat()
        self.drop("health", f"health-{wed:%Y-%m-%d}-085500.json")
        self.planner.fail = True
        self.assertEqual(self.tick(wed), [])
        self.assertIn("health", self.state()["requested"])
        self.planner.fail = False
        self.assertEqual(self.tick(wed + timedelta(hours=1)), ["refreshed after health"])
        self.assertEqual(self.state()["requested"], {})
        self.assertNotIn("error", self.state())

    def plan(self, key, folder="plans", text="Mon: lift"):
        path = self.var / "training" / folder / f"{key}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def show(self, spec, at=SUN):
        deliver.show(spec, self.phone, now=at, var=self.var)
        return self.phone.texts[-1]

    def test_plan_shows_this_week_next_week_or_a_named_one(self):
        self.plan("2026-W46", text="this week")
        self.plan("2026-W47", text="next week")
        self.assertIn("Plan for 2026-W46:\n\nthis week", self.show(""))
        self.assertIn("next week", self.show("next"))
        self.assertIn("next week", self.show("2026-w47"))
        self.assertEqual(self.planner.calls, [])

    def test_plan_falls_back_to_an_imported_note_without_its_comment(self):
        self.plan("2026-W46", "history", "<!-- Imported from Drive -->\n# Week 1")
        self.assertEqual(self.show(""), "Plan for 2026-W46:\n\n# Week 1")
        self.plan("2026-W46", text="lab plan")
        self.assertIn("lab plan", self.show(""))

    def test_plan_says_when_there_is_none_or_the_week_is_unreadable(self):
        self.assertEqual(self.show("next"), "No plan for 2026-W47 yet.")
        self.assertIn("Which week?", self.show("tomorrow"))
        self.assertIn("Which week?", self.show("2026-W99"))

    def test_plan_texts_end_with_the_remote_link_when_one_is_set(self):
        self.plan("2026-W46")
        with mock.patch.dict(os.environ, {"RUSH_REMOTE_URL": "http://mac.ts.net/"}):
            self.assertTrue(self.show("").endswith("\n\nhttp://mac.ts.net/training/2026-W46"))

    def sick(self, text, today):
        return [{"kind": "sick", "date": today.isoformat(), "end_date": None, "start": None,
                 "end": None, "minutes": None, "effort": None, "done": False, "what": text}]  # fmt: skip

    def test_a_note_is_echoed_and_replans_only_when_asked(self):
        self.fresh()
        self.tick(SUN.replace(hour=19))  # W47 sent
        at = SUN.replace(hour=21)
        deliver.note("a cold", self.phone, at, self.var, self.sick)
        self.assertTrue(self.phone.said("Sun Nov 15: sick (a cold)"))
        self.assertEqual(len(self.planner.calls), 1)
        deliver.note("flu", self.phone, at, self.var, self.sick, self.planner, then_replan=True)
        self.assertEqual(len(self.planner.calls), 2)
        self.assertTrue(self.phone.said("Updated plan:"))
        deliver.unnote(self.phone, at, self.var)
        self.assertEqual(self.phone.texts[-1], "Dropped: flu")

    def test_a_note_that_cannot_be_read_is_not_saved(self):
        def broken(text, today):
            raise ValueError("no JSON array in the reply")

        deliver.note("mumble", self.phone, SUN, self.var, broken)
        self.assertTrue(self.phone.said("Couldn't read that note"))
        deliver.unnote(self.phone, SUN, self.var)
        self.assertEqual(self.phone.texts[-1], "No notes to drop.")

    def test_a_work_hours_note_is_read_and_replanned_by_the_next_tick_after(self):
        self.fresh()
        self.tick(SUN.replace(hour=19))  # W47 sent
        wed = SUN + timedelta(days=3, hours=10)  # Wed Nov 18, 10:00
        deliver.note("flu", self.phone, wed, self.var, self.sick, then_replan=True)
        self.assertTrue(self.phone.said("No local model runs in work hours"))
        self.assertEqual(len(self.planner.calls), 1)
        done = deliver.tick(
            self.phone, now=wed.replace(hour=17), planner=self.planner, var=self.var,
            parser=self.sick,
        )  # fmt: skip
        self.assertEqual(done, ["read a note", "replanned after a note"])
        self.assertTrue(self.phone.said("Wed Nov 18: sick (flu)"))
        self.assertEqual(self.planner.calls[-1], ("2026-W47", date(2026, 11, 19)))

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
