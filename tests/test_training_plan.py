import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from light_labs.core import gate
from light_labs.training import plan

MON = date(2026, 11, 16)
GOALS = "# Goals\n- Week 1 starts Monday 2026-11-09. Weeks run Monday–Sunday.\n"


def lift(name, week, weight, reps, pattern="horizontal_push", bodyweight=False):
    return {
        "exercise": name,
        "movement_pattern": pattern,
        "is_bodyweight_lift": bodyweight,
        "week_start": week,
        "last_session_date": week + timedelta(days=2),
        "top_set_weight": weight,
        "top_set_reps": reps,
    }


def ctx():
    days = []
    for i in range(7):
        d = MON + timedelta(days=i)
        days.append(
            {
                "date": d.isoformat(),
                "weekday": d.strftime("%a"),
                "free": [["05:00", "21:00"]],
                "weather": {"outdoor_windows": [["12:00", "17:00"]], "outdoor_ok": True},
            }
        )
    return {"week": "2026-W47", "days": days}


def good_plan(load=165):
    days = []
    for i in range(7):
        d = (MON + timedelta(days=i)).isoformat()
        if i in (3, 6):
            days.append({"date": d, "rest": True, "slot": None, "items": []})
        elif i == 1:
            days.append(
                {"date": d, "rest": False, "slot": ["13:00", "13:45"], "type": "run",
                 "outdoor": True, "title": "Easy run", "items": [{"text": "45 min easy"}]}
            )  # fmt: skip
        else:
            days.append(
                {"date": d, "rest": False, "slot": ["05:30", "06:30"], "type": "lift",
                 "outdoor": False, "title": "Strength",
                 "items": [{"exercise": "Bench Press (Barbell)", "sets": 4, "reps": 5,
                            "load_lb": load}]}
            )  # fmt: skip
    return {"glance": "Week 2: 4 lifts, 1 run.", "days": days, "summary": {"cue": "Brace."}}


class NumbersTest(unittest.TestCase):
    def test_week_number_and_deload(self):
        self.assertEqual(plan.week_number(MON, GOALS), 2)
        self.assertEqual(plan.deload(4, 0.9)[0], True)
        self.assertEqual(plan.deload(5, 1.4)[0], True)
        self.assertEqual(plan.deload(5, 1.2), (False, ""))
        with self.assertRaises(LookupError):
            plan.week_number(MON, "# no week line")

    def test_progression_keeps_the_logged_scheme(self):
        w1, w2 = MON - timedelta(days=14), MON - timedelta(days=7)
        lifts = [
            lift("Bench Press (Barbell)", w1, 155, 5),
            lift("Bench Press (Barbell)", w2, 160, 5),  # hit 5 → +5
            lift("Bicep Curl (Dumbbell)", w2, 27.5, 10, "arms"),  # per hand → +2.5
            lift("Squat (Barbell)", w1, 165, 5, "squat"),
            lift("Squat (Barbell)", w2, 170, 4, "squat"),  # short of 5 → repeat
            lift("Pull Up", w2, 0, 3, "vertical_pull", bodyweight=True),
            lift("Box Squat (Barbell)", MON - timedelta(weeks=20), 45, 5, "squat"),  # stale
        ]
        rows = {r["exercise"]: r for r in plan.progression(lifts, MON, is_deload=False)}
        self.assertEqual(
            (rows["Bench Press (Barbell)"]["load_lb"], rows["Bench Press (Barbell)"]["reps"]),
            (165, 5),
        )
        self.assertEqual(rows["Bicep Curl (Dumbbell)"]["load_lb"], 30)
        self.assertTrue(rows["Bicep Curl (Dumbbell)"]["per_hand"])
        self.assertEqual(
            (rows["Squat (Barbell)"]["load_lb"], rows["Squat (Barbell)"]["reps"]), (170, 5)
        )
        self.assertEqual((rows["Pull Up"]["load_lb"], rows["Pull Up"]["reps"]), (None, 4))
        self.assertNotIn("Box Squat (Barbell)", rows)

    def test_deload_takes_ninety_percent_on_the_right_step(self):
        w = MON - timedelta(days=7)
        lifts = [
            lift("Bench Press (Barbell)", w, 160, 5),
            lift("Bicep Curl (Dumbbell)", w, 27.5, 10),
        ]
        rows = {r["exercise"]: r["load_lb"] for r in plan.progression(lifts, MON, is_deload=True)}
        self.assertEqual(rows, {"Bench Press (Barbell)": 150, "Bicep Curl (Dumbbell)": 27.5})

    def test_assumed_work_hours_leave_weekends(self):
        c = plan.with_assumed_work(ctx(), "08:00-17:00")
        self.assertEqual(c["days"][0]["free"], [["05:00", "08:00"], ["17:00", "21:00"]])
        self.assertEqual(c["days"][5]["free"], [["05:00", "21:00"]])
        self.assertEqual(plan.with_assumed_work(ctx(), "")["days"][0]["free"], [["05:00", "21:00"]])


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.table = [{"exercise": "Bench Press (Barbell)", "reps": 5, "load_lb": 165}]

    def test_a_good_plan_passes(self):
        self.assertEqual(plan.check(good_plan(), ctx(), self.table), [])

    def test_each_rule_catches_its_failure(self):
        p = good_plan(load=170)
        p["days"][3]["rest"] = False  # 6 training days
        p["days"][3]["slot"] = ["04:00", "05:00"]  # before the free window
        p["days"][1]["slot"] = ["08:00", "08:45"]  # outdoor run in the cold morning
        fails = "\n".join(plan.check(p, ctx(), self.table))
        self.assertIn("6 training days", fails)
        self.assertIn("not inside a free window", fails)
        self.assertIn("outdoor hours", fails)
        self.assertIn("the table says 165", fails)


class FakeBrain:
    def __init__(self, replies):
        self.replies, self.asked = list(replies), []

    def think(self, system, user, **_):
        self.asked.append(user)
        return self.replies.pop(0)


class RunTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.var = Path(tmp.name)
        (self.var / "training").mkdir()
        (self.var / "training" / "goals.md").write_text(GOALS)
        marts = mock.patch.object(
            plan, "read_marts",
            return_value=([lift("Bench Press (Barbell)", MON - timedelta(days=7), 160, 5)],
                          [{"iso_week": "2026-W46", "acute_chronic_ratio": 0.8}]),
        )  # fmt: skip
        marts.start()
        self.addCleanup(marts.stop)
        work = mock.patch.object(plan, "ASSUME_WORK", "")  # the fixture's week is all free
        work.start()
        self.addCleanup(work.stop)

    def test_retries_once_with_the_failures_then_writes(self):
        brain = FakeBrain([json.dumps(good_plan(load=170)), json.dumps(good_plan())])
        out, fails = plan.run("2026-W47", brain=brain, var=self.var, ctx=ctx())
        self.assertEqual(fails, [])
        self.assertIn("the table says 165", brain.asked[1])
        text = out.read_text()
        self.assertTrue(text.startswith("# Week 2 (2026-W47, Nov 16–Nov 22)"))
        self.assertIn("Bench Press (Barbell) 4x5 @ 165 lb", text)
        self.assertIn("(outdoor)", text)
        self.assertNotIn("Checks that failed", text)

    def test_still_failing_plans_are_written_with_their_failures(self):
        bad = json.dumps(good_plan(load=170))
        out, fails = plan.run("2026-W47", brain=FakeBrain([bad, bad]), var=self.var, ctx=ctx())
        self.assertTrue(fails)
        self.assertIn("## Checks that failed", out.read_text())

    def test_reply_without_json_is_retried(self):
        brain = FakeBrain(
            ["Sure! Here's your plan.", "```json\n" + json.dumps(good_plan()) + "\n```"]
        )
        _, fails = plan.run("2026-W47", brain=brain, var=self.var, ctx=ctx())
        self.assertEqual(fails, [])


class GateTest(unittest.TestCase):
    def test_training_plan_is_a_known_source_that_carries_nothing_denied(self):
        self.assertEqual(gate.carries(plan.SOURCE), set())


class ConnectTest(unittest.TestCase):
    def setUp(self):
        import duckdb

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "lab.duckdb"
        duckdb.connect(str(self.db)).close()
        self.duckdb, self.real = duckdb, duckdb.connect

    def locked(self, times):
        left = [times]

        def connect(path, read_only=False):
            if left[0]:
                left[0] -= 1
                raise self.duckdb.IOException("IO Error: Could not set lock on file")
            return self.real(path, read_only=read_only)

        return mock.patch.object(self.duckdb, "connect", connect)

    def test_waits_for_a_writer_to_finish(self):
        naps = []
        with self.locked(2), plan._connect(self.db, sleep=naps.append) as con:
            self.assertEqual(con.execute("SELECT 1").fetchone()[0], 1)
        self.assertEqual(naps, [plan.LOCK_STEP] * 2)

    def test_gives_up_after_the_wait(self):
        naps = []
        with self.locked(99), self.assertRaises(self.duckdb.IOException):
            plan._connect(self.db, wait=plan.LOCK_STEP * 3, sleep=naps.append)
        self.assertEqual(len(naps), 3)

    def test_other_io_errors_are_not_retried(self):
        with self.assertRaises(self.duckdb.IOException):
            plan._connect(self.db.parent / "missing.duckdb", sleep=self.fail)


if __name__ == "__main__":
    unittest.main()
