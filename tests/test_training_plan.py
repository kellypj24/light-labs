import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from light_labs.core import gate
from light_labs.training import notes, plan

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

    def test_a_sick_week_holds_loads_and_reps(self):
        lifts = [
            lift("Bench Press (Barbell)", MON - timedelta(days=7), 160, 5),
            lift("Pull Up", MON - timedelta(days=7), 0, 4, "vertical_pull", bodyweight=True),
        ]
        rows = {r["exercise"]: r for r in plan.progression(lifts, MON, False, hold=True)}
        self.assertEqual(rows["Bench Press (Barbell)"]["load_lb"], 160)
        self.assertIn("held (sick)", rows["Bench Press (Barbell)"]["rule"])
        self.assertEqual(rows["Pull Up"]["reps"], 4)
        moving = {r["exercise"]: r for r in plan.progression(lifts, MON, False)}
        self.assertEqual(moving["Bench Press (Barbell)"]["load_lb"], 165)
        self.assertEqual(moving["Pull Up"]["reps"], 5)

    def test_progression_keeps_the_logged_scheme(self):
        w1, w2 = MON - timedelta(days=14), MON - timedelta(days=7)
        lifts = [
            lift("Bench Press (Barbell)", w1, 155, 5),
            lift("Bench Press (Barbell)", w2, 160, 5),  # hit 5 → +5
            lift("Bicep Curl (Dumbbell)", w2, 27.5, 10, "arms"),  # per hand → +2.5
            lift("Squat (Barbell)", w1, 165, 5, "squat"),
            lift("Squat (Barbell)", w2, 170, 4, "squat"),  # short of 5 → repeat
            lift("Pull Up", w2, 0, 3, "vertical_pull", bodyweight=True),
            lift("Box Squat (Barbell)", MON - timedelta(weeks=30), 45, 5, "squat"),  # stale
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

    def test_habit_is_the_logged_session_and_the_rotation_oldest_first(self):
        def workout(n, name, day, *exercises, sets=4):
            return [
                {"workout_id": n, "workout_name": name, "workout_date": day, "exercise": e,
                 "working_sets": sets}
                for e in exercises
            ]  # fmt: skip

        d = date(2026, 8, 1)
        rows = (
            workout(1, "Mix 1A", d, "Bench Press (Dumbbell)", "Bulgarian Split Squat")
            + [
                {
                    "workout_id": 2,
                    "workout_name": "Mix 1B",
                    "workout_date": d + timedelta(days=5),
                    "exercise": e,
                    "working_sets": 4,
                    "movement_pattern": p,
                }
                for e, p in (("Pull Up", "vertical_pull"), ("Skullcrusher (Dumbbell)", "arms"))
            ]
            + workout(3, "Mix 2A", d + timedelta(days=9), "Squat (Barbell)", "Shrug (Barbell)")
            + workout(4, "Mix 1A", d + timedelta(days=90), "Bench Press (Dumbbell)", "Dip", "Curl")
        )
        h = plan.habit(rows)
        self.assertEqual((h["lifts"], h["sets"]), (2, 4))
        self.assertEqual([w["workout"] for w in h["pool"]], ["Mix 1B", "Mix 2A", "Mix 1A"])
        self.assertEqual(h["pool"][0]["lifts"], ["Pull Up", "Skullcrusher (Dumbbell)"])
        self.assertEqual(h["pool"][0]["patterns"], ["arms", "vertical_pull"])
        self.assertEqual(h["pool"][2]["lifts"], ["Bench Press (Dumbbell)", "Curl", "Dip"])
        self.assertEqual([w["workout"] for w in h["recent"]], ["Mix 1A", "Mix 2A"])
        many = [
            r for i in range(16) for r in workout(i, f"T{i:02d}", d + timedelta(days=i), "Squat")
        ]
        self.assertEqual(
            [w["workout"] for w in plan.habit(many)["pool"]], [f"T{i:02d}" for i in range(8)]
        )
        self.assertIsNone(plan.habit([]))

    def test_a_lift_day_is_one_pool_template_used_once(self):
        def day(i, *exercises):
            return {"date": (MON + timedelta(days=i)).isoformat(), "rest": False,
                    "slot": ["05:30", "06:15"], "type": "lift",
                    "items": [{"exercise": e, "sets": 4, "reps": 5} for e in exercises]
                    + [{"text": "Bag 4x3 min"}]}  # fmt: skip

        shape = {"lifts": 2, "sets": 4, "pool": [
            {"workout": "Mix 1B", "lifts": ["Pull Up", "Skullcrusher (Dumbbell)"]},
            {"workout": "Mix 2A", "lifts": ["Incline Bench Press (Dumbbell)", "RDL"]},
        ]}  # fmt: skip
        week = good_plan()
        week["days"][0] = day(0, "Skullcrusher (Dumbbell)", "Pull Up")
        week["days"][2] = day(2, "RDL", "Incline Bench Press (Dumbbell)")
        week["days"][4] = day(4, "Pull Up", "Skullcrusher (Dumbbell)")
        week["days"][5] = day(5, "Pull Up", "RDL")
        fails = plan.check(week, ctx(), [], shape=shape)
        self.assertEqual(
            fails,
            [
                "2026-11-20: Mix 1B is already on another day this week",
                "2026-11-21: its lifts are not one template from the pool (Mix 1B, Mix 2A)",
            ],
        )

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

    def test_a_lift_session_larger_than_the_habit_fails(self):
        p = good_plan()
        shape = {"lifts": 2, "sets": 4, "pool": []}
        self.assertEqual(plan.check(p, ctx(), self.table, shape=shape), [])
        bench = p["days"][0]["items"][0]
        p["days"][0]["items"] += [{**bench, "sets": 5}, bench, {"text": "Bag 4x3 min"}]
        fails = "\n".join(plan.check(p, ctx(), self.table, shape=shape))
        self.assertIn("2026-11-16: 3 lifts; PJ's sessions have 2 at most", fails)
        self.assertIn("for 5 sets; PJ does 4 at most", fails)


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
        sessions = mock.patch.object(
            plan, "read_sessions",
            return_value=[{"workout_id": 1, "workout_name": None, "workout_date": MON,
                           "exercise": "Bench Press (Barbell)", "working_sets": 4}],
        )  # fmt: skip
        sessions.start()
        self.addCleanup(sessions.stop)
        work = mock.patch.object(plan, "ASSUME_WORK", "")  # the fixture's week is all free
        work.start()
        self.addCleanup(work.stop)

    def test_retries_once_with_the_failures_then_writes(self):
        brain = FakeBrain([json.dumps(good_plan(load=170)), json.dumps(good_plan())])
        out, fails = plan.run("2026-W47", brain=brain, var=self.var, ctx=ctx())
        self.assertEqual(fails, [])
        self.assertIn("the table says 165", brain.asked[1])
        self.assertIn("1 lifts a session, 4 working sets each", brain.asked[0])
        self.assertIn("Template pool, longest since done first:", brain.asked[0])
        text = out.read_text()
        self.assertTrue(text.startswith("# Week 2 (2026-W47, Nov 16–Nov 22)"))
        self.assertIn("Bench Press (Barbell) 4x5 @ 165 lb", text)
        self.assertIn("(outdoor)", text)
        self.assertNotIn("Checks that failed", text)

    def test_notes_change_the_windows_and_the_sessions_owed_before_the_model_is_asked(self):
        def parser(text, today):
            base = dict.fromkeys(("end_date", "start", "end", "minutes", "effort"))
            return [
                {**base, "kind": "sick", "date": "2026-11-17", "done": False, "what": "stomach bug"},
                {**base, "kind": "event", "date": "2026-11-18", "start": "06:00", "end": "08:00",
                 "done": False, "what": "dentist"},
            ]  # fmt: skip

        notes.add("x", datetime(2026, 11, 15, 12), self.var, parser)
        brain = FakeBrain([json.dumps(good_plan())] * 2)
        plan.run("2026-W47", brain=brain, var=self.var, ctx=ctx())
        asked = brain.asked[0]
        self.assertIn("Plan exactly 4 training days.", asked)
        self.assertIn("Notes from PJ", asked)
        self.assertIn("2026-11-17 sick", asked)
        for word in ("stomach bug", "dentist"):
            self.assertNotIn(word, asked)
        days = {
            d["date"]: d for d in json.loads(asked.split("per day:\n")[1].split("\n\nNotes")[0])
        }
        self.assertEqual(days["2026-11-17"]["free"], [])
        self.assertNotIn(["06:00", "08:00"], days["2026-11-18"]["free"])
        self.assertTrue(all(a >= "08:00" or b <= "06:00" for a, b in days["2026-11-18"]["free"]))

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
