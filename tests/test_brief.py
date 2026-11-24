import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from unittest import mock

from light_labs.agents.rush import brief
from light_labs.core import gate, mcp_server

NOW = datetime(2026, 11, 24, 12, 50, tzinfo=UTC)
NO_READERS = {}


class FakeBrain:
    def __init__(self, answer="Reply to Acme today.\nQueue: 1 waiting.", error=None):
        self.answer, self.error, self.seen = answer, error, None

    def think(self, system, user, **_):
        self.seen = user
        if self.error:
            raise self.error
        return self.answer


class FakeTelegram:
    def __init__(self):
        self.texts, self.drafts = [], []

    def text(self, to, text):
        self.texts.append(text)

    def draft(self, item, text):
        self.drafts.append(item["id"])


class BriefTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.var = Path(tmp.name)
        patch = mock.patch.object(mcp_server.config, "VAR", self.var)
        patch.start()
        self.addCleanup(patch.stop)

    def mail(self, *rows):
        path = self.var / "rush" / "mail" / "pj@example.com.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for i, row in enumerate(rows):
            at = NOW - timedelta(hours=row.pop("hours_ago", 2))
            lines.append(json.dumps({"id": f"m{i}", "account": "pj@example.com",
                                     "date": format_datetime(at), "label": "needs_reply",
                                     "summary": "", **row}))  # fmt: skip
        path.write_text("\n".join(lines) + "\n")

    def pending(self, robot, id, created="2026-11-20T10:00:00+00:00", **extra):
        path = self.var / robot / "queue" / "pending" / f"{id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        item = {"id": id, "kind": "reply", "target": {"task_id": "t1"}, "draft": "secret draft",
                "context": "Dana: hello", "created": created, **extra}  # fmt: skip
        path.write_text(json.dumps(item))

    def test_personal_mail_and_client_repos_never_reach_claude(self):
        self.mail(
            {"from": "Acme Billing <billing@acme.com>", "subject": "Invoice 42 due Friday"},
            {"from": "Dana Whitfield <dana@gmail.com>", "subject": "Charlotte's party"},
        )
        status = {
            "open_prs": [
                {"repo": "kellypj24/recoup", "number": 7, "checks_failing": 1},
                {"repo": "kellypj24/scouter", "number": 22, "checks_failing": 2},
            ],
            "ci_failing": {"kellypj24/dentasys-modernization": ["CI"]},
        }
        brain = FakeBrain()
        text, ids = brief.compose(NOW, brain, {"github": lambda: brief.github(status)})
        self.assertIn("Acme Billing", brain.seen)
        self.assertIn("scouter", brain.seen)
        for private in ("Dana", "Charlotte", "recoup", "dentasys"):
            self.assertNotIn(private, brain.seen)
        self.assertEqual(gate.evaluate(brief.SOURCE, brain.seen).hits, {})
        self.assertIn("Reply: Dana Whitfield: Charlotte's party", text)
        self.assertIn("kellypj24/recoup #7: 1 check(s) failing", text)
        self.assertIn("CI failing on kellypj24/dentasys-modernization: CI", text)
        self.assertEqual(set(ids), {"m0", "m1"})

    def test_mail_is_recent_needs_reply_or_a_deadline(self):
        self.mail(
            {"from": "A <a@acme.com>", "subject": "old", "hours_ago": 40},
            {"from": "B <b@acme.com>", "subject": "Weekly digest", "label": "fyi"},
            {"from": "C <c@acme.com>", "subject": "Your bill is due", "label": "receipt"},
            {"from": "D <d@acme.com>", "subject": "Payment deals!", "label": "newsletter"},
            {"from": "E <e@acme.com>", "subject": "Can you confirm?"},
        )
        safe, local = brief.mail(NOW)
        self.assertEqual([m["subject"] for m in safe], ["Can you confirm?", "Your bill is due"])
        self.assertEqual(local, [])

    def test_a_thread_flagged_yesterday_is_still_open(self):
        self.mail({"from": "E <e@acme.com>", "subject": "Can you confirm?"})
        text, ids = brief.compose(NOW, None, NO_READERS)
        brief.send(text, ids, NOW, FakeTelegram())
        text, _ = brief.compose(NOW + timedelta(hours=20), None, NO_READERS)
        self.assertIn("Can you confirm? [still open]", text)

    def test_claude_failing_still_briefs_and_says_why(self):
        self.mail({"from": "E <e@acme.com>", "subject": "Can you confirm?"})
        brain = FakeBrain(error=RuntimeError("claude -p failed: Invalid API key"))
        text, _ = brief.compose(NOW, brain, NO_READERS)
        self.assertIn("Reply: E: Can you confirm?", text)
        self.assertIn("Written without Claude (RuntimeError: claude -p failed", text)

    def test_a_failing_reader_costs_only_its_section(self):
        def down():
            raise TimeoutError("edge")

        text, _ = brief.compose(NOW, None, {"board": down, "weather": lambda: None})
        self.assertIn("No board this run (TimeoutError).", text)

    def test_claude_is_held_to_the_line_budget(self):
        self.mail({"from": "E <e@acme.com>", "subject": "Can you confirm?"})
        brain = FakeBrain(answer="\n".join(f"line {i}" for i in range(30)))
        text, _ = brief.compose(NOW, brain, NO_READERS)
        self.assertEqual(len(text.splitlines()), brief.WRITTEN_LINES)

    def test_queue_counts_reach_claude_without_draft_text(self):
        self.pending("rush", "a1", escalate="needs PJ")
        self.pending("roll", "b1", created="2026-11-22T10:00:00+00:00")
        brain = FakeBrain()
        brief.compose(NOW, brain, NO_READERS)
        self.assertNotIn("secret draft", brain.seen)
        q = brief.queue(NOW)
        self.assertEqual(q["by_robot"], {"rush": 1, "roll": 1})
        self.assertEqual(
            (q["escalated"], q["oldest"]["robot"], q["oldest"]["days"]), (1, "rush", 4)
        )

    def test_rush_is_flagged_when_stale_or_in_trouble_lately(self):
        root = self.var / "rush"
        root.mkdir(parents=True)
        (root / "state.json").write_text(json.dumps({"updated_at": "2026-11-24T06:07:00+00:00"}))
        (root / "journal.md").write_text(
            "- 2026-11-24T04:30:00+00:00 GitHub check failed: reset\n"
            "- 2026-11-24T12:07:00+00:00 edge unreachable\n"
        )
        (line,) = brief.robots(NOW)
        self.assertIn("Rush: no tick since Tue 01:07", line)
        self.assertIn("1 trouble line(s) in the journal, last: edge unreachable", line)

    def test_send_texts_the_brief_then_rushs_oldest_drafts(self):
        for n in range(5):
            self.pending("rush", f"r{n}", created=f"2026-11-2{n}T10:00:00+00:00")
        self.pending("roll", "x1", created="2026-11-01T10:00:00+00:00")
        telegram = FakeTelegram()
        shown = brief.send("the brief", ["m1"], NOW, telegram)
        self.assertEqual(telegram.texts, ["the brief"])
        self.assertEqual(shown, ["r0", "r1", "r2"])
        self.assertEqual(telegram.drafts, shown)
        state = json.loads((self.var / "rush" / "brief" / "state.json").read_text())
        self.assertEqual(state, {"date": "2026-11-24", "flagged": ["m1"]})
        self.assertEqual(
            (self.var / "rush" / "brief" / "2026-11-24.txt").read_text(), "the brief\n"
        )

    def events(self, *rows):
        day = "2026-11-24"
        out = []
        for start, end, title, family in rows:
            all_day = start is None
            out.append({
                "start": brief.date.fromisoformat(day) if all_day
                else brief._at(f"{start}:00-05:00" if "T" in start else f"{day}T{start}:00-05:00"),
                "end": brief.date.fromisoformat("2026-11-25") if all_day
                else brief._at(f"{end}:00-05:00" if "T" in end else f"{day}T{end}:00-05:00"),
                "all_day": all_day, "title": title, "where": "", "family": family,
            })  # fmt: skip
        return out

    def test_calendar_titles_stay_local_and_claude_gets_the_shape(self):
        found = self.events(
            (None, None, "Trash day", True),
            ("08:30", "09:30", "Standup", False),
            ("09:30", "10:00", "Dentasys sync", False),
            ("09:45", "10:15", "School drop-off", True),
            ("10:00", "11:00", "Review", False),
            ("2026-11-25T08:00", "2026-11-25T09:00", "Dentist", True),
        )
        brain = FakeBrain()
        text, _ = brief.compose(NOW, brain, {"calendar": lambda: brief.calendar(NOW, found)})
        for title in ("Standup", "Dentasys", "drop-off", "Dentist", "Trash"):
            self.assertNotIn(title, brain.seen)
        shape = json.loads(brain.seen.split("<facts>")[1].split("</facts>")[0])["calendar"]
        self.assertEqual(shape["events_today"], 4)
        self.assertEqual(shape["starts_before_9"], ["08:30"])
        self.assertEqual(shape["conflicts_work_vs_family"], ["09:30–10:00 overlaps 09:45–10:15",
                                                             "10:00–11:00 overlaps 09:45–10:15"])  # fmt: skip
        self.assertEqual(shape["tomorrow_morning_first"], "08:00")
        self.assertIn("All day Trash day (family)", text)
        self.assertIn("09:45–10:15 School drop-off (family)", text)
        self.assertIn("Conflict: 09:30 Dentasys sync overlaps 09:45 School drop-off (family)", text)
        self.assertIn("Tomorrow morning: 08:00 Dentist", text)

    def test_three_events_without_a_break_are_a_stretch(self):
        found = self.events(
            ("13:00", "14:00", "A", False),
            ("14:00", "15:00", "B", False),
            ("15:05", "16:00", "C", False),
            ("17:00", "18:00", "D", False),
        )
        safe, _ = brief.calendar(NOW, found)
        self.assertEqual(safe["no_break_stretches"], ["13:00–16:00"])
        self.assertIn("No break 13:00–16:00", brief.render({"calendar": safe}))

    def test_events_come_from_each_named_calendar_with_family_tagged(self):
        class Cal:
            def resolve(self, names):
                return [f"id-{n}" for n in names]

            def events(self, cal_id, start, end):
                self.window = (start.isoformat(), end.isoformat())
                return [{"start": "2026-11-24T09:00:00-05:00", "end": "2026-11-24T10:00:00-05:00",
                         "all_day": False, "title": cal_id, "where": ""}]  # fmt: skip

        cal = Cal()
        found = brief.events(NOW, cal, ["primary", "Kelly family calendar"])
        self.assertEqual([(e["title"], e["family"]) for e in found],
                         [("id-primary", False), ("id-Kelly family calendar", True)])  # fmt: skip
        self.assertEqual(cal.window, ("2026-11-24T00:00:00-05:00", "2026-11-25T12:00:00-05:00"))

    def test_nothing_to_say(self):
        text, ids = brief.compose(NOW, FakeBrain(), NO_READERS)
        self.assertEqual((text, ids), ("Nothing needs you this morning.", []))


if __name__ == "__main__":
    unittest.main()
