import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from light_labs.training import notes, plan

SAT = date(2026, 11, 14)
NOON = datetime(2026, 11, 14, 12, 0)


def raw(**kw):
    base = dict.fromkeys(("end_day", "start", "end", "minutes", "effort"))
    return {**base, "kind": "event", "day": "today", "done": False, "what": "thing", **kw}


def row(**kw):
    return notes.clean(raw(**kw), SAT)


class FakeBrain:
    def __init__(self, reply):
        self.reply, self.asked = reply, []

    def think(self, system, user, temperature=None):
        self.asked.append(user)
        return self.reply


class ResolveTest(unittest.TestCase):
    def test_day_words(self):
        for word, done, want in [
            ("today", False, "2026-11-14"),
            ("yesterday", True, "2026-11-13"),
            ("tomorrow", False, "2026-11-15"),
            ("Thu", False, "2026-11-19"),  # upcoming: the next Thursday
            ("thursday", True, "2026-11-12"),  # done: the last one
            ("sat", True, "2026-11-14"),  # today counts either way
            ("2026-12-03", False, "2026-12-03"),
        ]:
            self.assertEqual(notes.resolve(word, SAT, done).isoformat(), want, word)
        self.assertIsNone(notes.resolve("someday", SAT))
        self.assertIsNone(notes.resolve("2026-13-40", SAT))

    def test_a_span_ends_on_or_after_its_first_day(self):
        r = row(kind="travel", day="thu", end_day="sun")
        self.assertEqual((r["date"], r["end_date"]), ("2026-11-19", "2026-11-22"))


class CleanTest(unittest.TestCase):
    def test_a_start_without_an_end_gets_the_duration_or_an_hour(self):
        self.assertEqual(row(start="16:00")["end"], "17:00")
        self.assertEqual(row(start="16:00", minutes=30)["end"], "16:30")
        self.assertEqual(row(start="9:05", end="10:00")["start"], "09:05")

    def test_fields_the_model_got_wrong_are_dropped_not_trusted(self):
        r = row(kind="party", start="25:00", end="x", minutes="lots", effort="brutal", day="soon")
        self.assertEqual(
            (r["kind"], r["start"], r["end"], r["minutes"], r["effort"], r["date"]),
            ("other", None, None, None, None, "2026-11-14"),
        )
        self.assertIsNone(row(start="17:00", end="15:00")["start"])
        self.assertIsNone(notes.clean("not an object", SAT))

    def test_a_past_day_is_done_whatever_the_model_said(self):
        self.assertTrue(row(day="yesterday", done=False)["done"])

    def test_parse_reads_the_array_out_of_the_reply(self):
        brain = FakeBrain("Here you go:\n" + json.dumps([raw(kind="sick", what="flu")]))
        rows = notes.parse("flu", SAT, brain)
        self.assertEqual([r["kind"] for r in rows], ["sick"])
        self.assertIn("Today is Saturday 2026-11-14.\nNote: flu", brain.asked[0])
        with self.assertRaises(ValueError):
            notes.parse("flu", SAT, FakeBrain("I can't help with that."))


class RecordTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.var = Path(tmp.name)

    def parser(self, text, today):
        return [row(kind="chore", what=text, day=today.isoformat())]

    def test_add_load_and_undo(self):
        notes.add("mowed", NOON, self.var, self.parser)
        notes.add("raked", NOON.replace(hour=13), self.var, self.parser)
        self.assertEqual([n["text"] for n in notes.load(self.var)], ["mowed", "raked"])
        self.assertEqual(notes.undo(NOON, self.var)["text"], "raked")
        self.assertEqual([n["text"] for n in notes.load(self.var)], ["mowed"])
        notes.undo(NOON, self.var)
        self.assertIsNone(notes.undo(NOON, self.var))

    def test_a_work_hours_note_is_saved_unread_and_read_after(self):
        wed = datetime(2026, 11, 11, 10, 0)  # a workday morning
        rec = notes.add("sick", wed, self.var, self.parser, replan=True)
        self.assertIsNone(rec["rows"])
        self.assertEqual(notes.read_unread(wed, self.var, self.parser), [])
        late = notes.read_unread(wed.replace(hour=17, minute=7), self.var, self.parser)
        self.assertEqual(late[0]["rows"][0]["date"], "2026-11-11")  # the day it was written
        self.assertTrue(late[0]["replan"])
        self.assertEqual(notes.read_unread(wed.replace(hour=18), self.var, self.parser), [])
        self.assertIsNotNone(notes.load(self.var)[0]["rows"])

    def test_rows_for_a_week_reach_back_one_week(self):
        for day in ("2026-11-02", "2026-11-12", "2026-11-18", "2026-11-25"):
            notes.add(day, NOON, self.var, lambda t, today: [row(day=t)])
        got = [r["date"] for r in notes.rows_for(date(2026, 11, 16), self.var)]
        self.assertEqual(got, ["2026-11-12", "2026-11-18"])


def ctx(*dates):
    return {"days": [{"date": d, "free": [["05:00", "21:00"]]} for d in dates]}

    def test_an_injury_reaches_every_later_week_until_recovered(self):
        notes.add("x", NOON, self.var, lambda t, today: [row(kind="injury", region="knee")])
        later = date(2026, 12, 14)
        self.assertEqual([r["kind"] for r in notes.rows_for(later, self.var)], ["injury"])
        self.assertEqual(notes.rows_for(date(2026, 11, 2), self.var), [])


class ApplyTest(unittest.TestCase):
    def apply(self, rows, train=5, days=("2026-11-14", "2026-11-15", "2026-11-16")):
        return notes.apply(ctx(*days), rows, train, plan.subtract)

    def test_an_upcoming_event_leaves_the_free_windows(self):
        out, owed, lines = self.apply([row(start="15:00", end="17:00")], train=3)
        self.assertEqual(out["days"][0]["free"], [["05:00", "15:00"], ["17:00", "21:00"]])
        self.assertEqual((owed, lines), (3, []))

    def test_a_sick_day_has_no_windows_and_the_week_owes_one_fewer(self):
        out, owed, lines = self.apply([row(kind="sick", end_day="sun")], train=3)
        self.assertEqual([d["free"] for d in out["days"][:2]], [[], []])
        self.assertEqual(owed, 1)
        self.assertEqual(lines[0], "2026-11-14 to 2026-11-15 sick")

    def test_upcoming_travel_days_have_no_windows_but_the_sessions_stay_owed(self):
        out, owed, lines = self.apply([row(kind="travel", end_day="sun")], train=1)
        self.assertEqual([d["free"] for d in out["days"][:2]], [[], []])
        self.assertEqual(owed, 1)
        self.assertEqual(lines, ["2026-11-14 to 2026-11-15 travel upcoming"])
        self.assertIn("no sessions those days", notes.echo([row(kind="travel", end_day="sun")]))

    def test_a_sick_day_holds_the_loads(self):
        self.assertTrue(notes.held([row(kind="sick")]))
        self.assertFalse(notes.held([row(kind="ache"), row(kind="travel")]))
        _, _, lines = self.apply([row(kind="sick")])
        self.assertIn("Loads are held", lines[-1])

    def test_an_injury_holds_loads_and_rules_out_its_region_until_recovered(self):
        hurt = row(kind="injury", region="Shoulder", what="sore shoulder")
        self.assertEqual(hurt["region"], "shoulder")
        self.assertTrue(notes.held([hurt]))
        _, owed, lines = self.apply([hurt], train=2)
        self.assertEqual(owed, 2)
        self.assertEqual(lines[0], "shoulder injury since 2026-11-14, not recovered")
        self.assertNotIn("sore", " ".join(lines))
        self.assertIn("until you send /note shoulder is fine", notes.echo([hurt]))
        healed = [hurt, row(kind="recovered", region="shoulder", day="tomorrow")]
        self.assertEqual((notes.injuries(healed), notes.held(healed)), ({}, False))

    def test_a_sore_body_part_is_an_injury_whatever_kind_the_model_gave(self):
        sore = row(kind="ache", what="sore shoulder")
        self.assertEqual((sore["kind"], sore["region"]), ("injury", "shoulder"))
        self.assertEqual(row(kind="ache", what="headache")["kind"], "ache")
        self.assertEqual(row(kind="injury", region="soul", what="tired")["kind"], "ache")

    def test_reasons_for_a_day_without_a_session(self):
        hurt = row(kind="injury", region="knee")  # noted Sat Nov 14
        chore = row(kind="chore", day="yesterday", what="mowed")
        week = "2026-11-09"
        self.assertEqual(notes.reasons([hurt, chore], "2026-11-13", week), ["knee injury", "chore"])
        self.assertEqual(notes.reasons([hurt], "2026-11-10", week), ["knee injury"])
        self.assertEqual(notes.reasons([hurt], "2026-11-06", week), [])
        self.assertEqual(notes.reasons([hurt], "2026-11-20", week), ["knee injury"])
        self.assertEqual(row(kind="recovered")["kind"], "other")
        self.assertIsNone(row(kind="chore", region="knee")["region"])

    def test_owed_never_exceeds_the_days_that_have_a_window(self):
        _, owed, _ = self.apply([], train=5)
        self.assertEqual(owed, 3)

    def test_chores_and_aches_reach_the_planner_without_their_words(self):
        rows = [
            row(kind="chore", day="yesterday", minutes=120, effort="hard", what="split firewood"),
            row(kind="ache", what="slept badly"),
            row(kind="event", start="15:00", end="17:00", what="dentist"),
        ]
        _, _, lines = self.apply(rows)
        self.assertEqual(lines, ["2026-11-13 chore 120 min hard done", "2026-11-14 ache upcoming"])
        self.assertNotIn("firewood", " ".join(lines))

    def test_echo_says_what_each_row_does(self):
        text = notes.echo([
            row(start="15:00", end="17:00", day="thu", what="dentist"),
            row(kind="chore", day="yesterday", minutes=120, effort="moderate", what="mowed"),
            row(kind="sick", what="cold"),
        ])  # fmt: skip
        self.assertIn("Thu Nov 19 15:00–17:00 busy (dentist)", text)
        self.assertIn("Fri Nov 13: mowed (chore, 120 min, moderate, done)", text)
        self.assertIn("Sat Nov 14: sick (cold). No session", text)
        self.assertIn("loads repeat", text)
        self.assertIn("/note undo", text)
        self.assertIn("couldn't find anything", notes.echo([]))


if __name__ == "__main__":
    unittest.main()
