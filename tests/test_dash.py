"""`lab dash`: parsing, state logic and key handling. No network, no terminal."""

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest import mock

from light_labs.core import google
from light_labs.dash import agenda, app, feed, labstate, render, review, sessions, tasks
from light_labs.training.calendar import TZ

NOW = datetime(2026, 11, 24, 10, 0, tzinfo=TZ)
TODAY = NOW.date()


def tasks_file(text):
    d = tempfile.TemporaryDirectory()
    path = Path(d.name) / "tasks.md"
    path.write_text(text)
    return d, path


class TaskParseTest(unittest.TestCase):
    def test_mine_waiting_and_due_dates(self):
        d, path = tasks_file(
            "# Tasks\n"
            "- [ ] renew registration (2026-12-01)\n"
            "- [x] done already (2026-11-01)\n"
            "- [ ] [[Ketan]] send the tailnet key\n"
            "  - [ ] nested, no date\n"
            "- [ ] [[ketan]] review the board (2026-11-20)\n"
            "- [ ]\n"
            "not a task\n"
        )
        self.addCleanup(d.cleanup)
        snap = tasks.read(path)
        mine = tasks.mine(snap)
        self.assertEqual([t.text for t in mine], ["renew registration", "nested, no date"])
        self.assertEqual(mine[0].due, date(2026, 12, 1))
        waiting = tasks.waiting(snap)
        self.assertEqual([t.who for t in waiting], ["ketan", "Ketan"])  # dated first
        self.assertEqual(waiting[0].text, "review the board")

    def test_a_date_that_is_not_a_date_stays_in_the_text(self):
        t = tasks.parse_line(0, "- [ ] call about invoice (2026-13-45)")
        self.assertIsNone(t.due)
        self.assertEqual(t.text, "call about invoice (2026-13-45)")

    def test_urgency(self):
        def due(day):
            return tasks.Task(0, "", "", None, day)

        self.assertEqual(tasks.urgency(due(TODAY - timedelta(days=1)), TODAY), "overdue")
        self.assertEqual(tasks.urgency(due(TODAY), TODAY), "soon")
        self.assertEqual(tasks.urgency(due(TODAY + timedelta(days=1)), TODAY), "soon")
        self.assertEqual(tasks.urgency(due(TODAY + timedelta(days=2)), TODAY), "")
        self.assertEqual(tasks.urgency(due(None), TODAY), "")

    def test_a_missing_file_is_an_empty_list(self):
        snap = tasks.read(Path(tempfile.gettempdir()) / "no-such-dir" / "tasks.md")
        self.assertEqual((snap.mtime_ns, snap.tasks), (None, ()))


class TaskWriteTest(unittest.TestCase):
    def setUp(self):
        self.d, self.path = tasks_file("- [ ] pay bill\r\n- [ ] pay bill twice\n- [ ] other")
        self.addCleanup(self.d.cleanup)
        self.snap = tasks.read(self.path)

    def test_check_changes_one_box_and_keeps_every_other_byte(self):
        tasks.check(self.snap, self.snap.tasks[1])
        self.assertEqual(
            self.path.read_bytes(), b"- [ ] pay bill\r\n- [x] pay bill twice\n- [ ] other"
        )

    def test_undo_restores_the_file(self):
        before = self.path.read_bytes()
        record = tasks.check(self.snap, self.snap.tasks[0])
        tasks.undo(record)
        self.assertEqual(self.path.read_bytes(), before)

    def test_no_write_when_the_file_changed_since_it_was_read(self):
        os.utime(self.path, ns=(1, self.snap.mtime_ns + 1_000_000_000))
        before = self.path.read_bytes()
        with self.assertRaises(tasks.Stale):
            tasks.check(self.snap, self.snap.tasks[0])
        self.assertEqual(self.path.read_bytes(), before)

    def test_no_write_on_a_prefix_match(self):
        # Same mtime, but the line now only starts with what was shown.
        self.path.write_text("- [ ] pay bill and the other one\n")
        os.utime(self.path, ns=(1, self.snap.mtime_ns))
        with self.assertRaises(tasks.Stale):
            tasks.check(self.snap, self.snap.tasks[0])
        self.assertEqual(self.path.read_text(), "- [ ] pay bill and the other one\n")

    def test_no_write_when_the_file_is_gone(self):
        self.path.unlink()
        with self.assertRaises(tasks.Stale):
            tasks.check(self.snap, self.snap.tasks[0])
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_a_symlink_stays_a_symlink_and_its_target_is_ticked(self):
        link = self.path.parent / "link.md"
        link.symlink_to(self.path)
        snap = tasks.read(link)
        tasks.check(snap, snap.tasks[2])
        self.assertTrue(link.is_symlink())
        self.assertTrue(self.path.read_text().endswith("- [x] other"))

    def test_a_file_that_stopped_being_text_is_stale_not_a_crash(self):
        self.path.write_bytes(b"- [ ] pay bill\xff\n")
        os.utime(self.path, ns=(1, self.snap.mtime_ns))
        with self.assertRaises(tasks.Stale):
            tasks.check(self.snap, self.snap.tasks[0])
        state = app.State(snapshot=self.snap)
        app.do_check(state, self.snap.tasks[0])
        self.assertIn("not checked", state.message)

    def test_undo_refuses_after_someone_else_wrote(self):
        record = tasks.check(self.snap, self.snap.tasks[0])
        os.utime(self.path, ns=(1, record["mtime_ns"] + 1_000_000_000))
        with self.assertRaises(tasks.Stale):
            tasks.undo(record)


STARTED = "Tue Nov 24 13:41:36 2026"


class SessionsTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name) / "sessions"
        self.projects = Path(d.name) / "projects"
        self.root.mkdir()
        (self.projects / "-p").mkdir(parents=True)

    def session(self, pid, sid, status, started=STARTED, at=0):
        rec = {"pid": pid, "sessionId": sid, "status": status, "procStart": started,
               "cwd": "/Users/pj/repo", "name": f"n{pid}", "statusUpdatedAt": at}  # fmt: skip
        (self.root / f"{pid}.json").write_text(json.dumps(rec))

    def log(self, sid, records):
        path = self.projects / "-p" / f"{sid}.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    def test_only_live_sessions_and_waiting_first(self):
        self.session(1, "aaa", "busy", at=1000)
        self.session(2, "bbb", "idle", at=3000)
        self.session(3, "ccc", "idle", at=2000)
        self.session(4, "ddd", "idle")  # process gone
        self.session(5, "eee", "idle", started="Mon Nov 23 01:00:00 2026")  # pid reused
        (self.root / "junk.json").write_text("{not json")
        starts = dict.fromkeys((1, 2, 3, 5), STARTED)
        live = sessions.live(self.root, self.projects, starts=lambda pids: starts)
        self.assertEqual([s["pid"] for s in live], [3, 2, 1])
        self.assertEqual([s["waiting"] for s in live], [True, True, False])

    def test_title_context_and_last_reply_come_from_the_log(self):
        self.session(1, "aaa", "idle")
        usage = {"input_tokens": 2, "cache_read_input_tokens": 1000,
                 "cache_creation_input_tokens": 500, "output_tokens": 9}  # fmt: skip
        self.log("aaa", [
            {"type": "ai-title", "aiTitle": "old title"},
            {"type": "assistant", "message": {"usage": {"input_tokens": 1},
                                              "content": [{"type": "text", "text": "early"}]}},
            {"type": "ai-title", "aiTitle": "new title"},
            {"type": "assistant", "message": {
                "usage": usage, "content": [{"type": "text", "text": "the\nanswer"}]}},
            {"type": "assistant", "isSidechain": True,
             "message": {"usage": {"input_tokens": 7},
                         "content": [{"type": "text", "text": "subagent"}]}},
        ])  # fmt: skip
        (s,) = sessions.live(self.root, self.projects, starts=lambda pids: {1: STARTED})
        self.assertEqual((s["title"], s["context"], s["reply"]), ("new title", 1502, "the answer"))

    def test_a_session_without_a_log_still_lists(self):
        self.session(1, "aaa", "idle")
        (s,) = sessions.live(self.root, self.projects, starts=lambda pids: {1: STARTED})
        self.assertEqual((s["title"], s["context"], s["reply"]), ("n1", None, ""))

    def test_a_cut_first_line_in_the_tail_is_skipped(self):
        # The tail starts inside the first record, at a point where what is left of it
        # is itself a whole record: only dropping the first line keeps "cut" out.
        path = self.projects / "-p" / "aaa.jsonl"
        kept = '{"type": "ai-title", "aiTitle": "cut"}\n{"type": "mode"}\n'
        path.write_text('{"type": "x", "nested": ' + kept)
        self.assertEqual(sessions.log_facts(sessions._tail(path, limit=len(kept))), {})
        self.assertEqual(sessions.log_facts(sessions._tail(path, limit=len(kept) + 500)), {})
        path.write_text(kept)
        self.assertEqual(sessions.log_facts(sessions._tail(path)), {"title": "cut"})

    def test_a_record_without_a_start_time_needs_a_matching_session_start(self):
        began = datetime(2026, 11, 24, 13, 41, 40, tzinfo=UTC).timestamp() * 1000
        for pid, extra in ((1, {"startedAt": began}), (2, {"startedAt": began + 9e6}), (3, {})):
            rec = {"pid": pid, "sessionId": f"s{pid}", "status": "idle", **extra}
            (self.root / f"{pid}.json").write_text(json.dumps(rec))
        live = sessions.live(
            self.root, self.projects, starts=lambda pids: dict.fromkeys(pids, STARTED)
        )
        self.assertEqual([s["pid"] for s in live], [1])

    def test_a_pid_that_is_not_a_positive_integer_is_not_a_session(self):
        for name, pid in (("a", True), ("b", 0), ("c", -4), ("d", "12")):
            (self.root / f"{name}.json").write_text(json.dumps({"pid": pid, "sessionId": "s"}))
        self.assertEqual(sessions.registry(self.root), [])


def event(summary, start, end, **extra):
    def point(v):
        return {"date": v} if len(v) == 10 else {"dateTime": v}

    return {"id": summary, "summary": summary, "start": point(start), "end": point(end), **extra}


class AgendaTest(unittest.TestCase):
    def rows(self, items, now=NOW):
        events = [e for e in (agenda.normalize(i, "primary") for i in items) if e]
        events.sort(key=lambda e: (not e["all_day"], e["start"]))
        return agenda.rows(events, now)

    def test_countdowns_and_focus_on_the_current_event(self):
        rows = self.rows([
            event("holiday", "2026-11-24", "2026-11-25"),
            event("early", "2026-11-24T08:00:00-05:00", "2026-11-24T09:00:00-05:00"),
            event("current", "2026-11-24T09:30:00-05:00", "2026-11-24T10:30:00-05:00"),
            event("later", "2026-11-24T12:10:00-05:00", "2026-11-24T13:00:00-05:00"),
        ])  # fmt: skip
        self.assertEqual([r["countdown"] for r in rows], ["today", "done", "now", "in 2h10m"])
        self.assertEqual([r["focus"] for r in rows], [False, False, True, False])
        self.assertEqual([r["n"] for r in rows], [1, 2, 3, 4])
        self.assertEqual(rows[2]["time"], "09:30-10:30")

    def test_focus_falls_to_the_next_event(self):
        rows = self.rows([
            event("early", "2026-11-24T08:00:00-05:00", "2026-11-24T09:00:00-05:00"),
            event("next", "2026-11-24T10:25:00-05:00", "2026-11-24T11:00:00-05:00"),
        ])  # fmt: skip
        self.assertEqual([(r["countdown"], r["focus"]) for r in rows],
                         [("done", False), ("in 25m", True)])  # fmt: skip

    def test_cancelled_and_declined_events_are_left_out(self):
        declined = [{"self": True, "responseStatus": "declined"}]
        others = [{"responseStatus": "declined"}, {"self": True, "responseStatus": "needsAction"}]
        t = ("2026-11-24T11:00:00-05:00", "2026-11-24T12:00:00-05:00")
        rows = self.rows([
            event("gone", *t, status="cancelled"),
            event("no", *t, attendees=declined),
            event("maybe", *t, attendees=others),
        ])  # fmt: skip
        self.assertEqual([(r["title"], r["unanswered"]) for r in rows], [("maybe", True)])

    def test_only_https_links_are_kept_and_a_join_link_wins(self):
        t = ("2026-11-24T11:00:00-05:00", "2026-11-24T12:00:00-05:00")
        page = "https://calendar.google.com/event?eid=1"
        cases = [
            ({"hangoutLink": "https://meet.google.com/abc", "htmlLink": page},
             ("https://meet.google.com/abc", True)),
            ({"location": "Zoom https://zoom.us/j/1 room 2", "htmlLink": page},
             ("https://zoom.us/j/1", True)),
            ({"location": "12 Main St", "htmlLink": page}, (page, False)),
            ({"location": "file:///etc/passwd", "htmlLink": "javascript:alert(1)"}, ("", False)),
        ]  # fmt: skip
        for extra, want in cases:
            e = agenda.normalize(event("e", *t, **extra), "primary")
            self.assertEqual((e["url"], e["join"]), want)

    def test_countdowns_are_right_across_a_daylight_saving_change(self):
        # 2026-11-01: 01:30 EDT, then the clocks go back at 02:00.
        now = datetime(2026, 11, 1, 5, 30, tzinfo=UTC).astimezone(TZ)
        later = event("later", "2026-11-01T03:00:00-05:00", "2026-11-01T04:00:00-05:00")
        ended = event("ended", "2026-11-01T01:00:00-04:00", "2026-11-01T01:20:00-04:00")
        second_hour = datetime(2026, 11, 1, 6, 10, tzinfo=UTC).astimezone(TZ)  # 01:10 EST
        self.assertEqual(self.rows([later], now)[0]["countdown"], "in 2h30m")
        self.assertEqual(self.rows([ended], second_hour)[0]["countdown"], "done")

    def test_fetch_reads_each_calendar_once_and_merges_duplicates(self):
        t = ("2026-11-24T11:00:00-05:00", "2026-11-24T12:00:00-05:00")

        asked = []

        class Cal:
            def resolve(self, names):
                return [f"id-{n}" for n in names]

            def events(self, cid, start, end):
                asked.append((cid, start, end))
                return [event("dinner", *t)] + ([event("mine", *t)] if cid == "id-primary" else [])

        got = agenda.fetch(TODAY, Cal(), ["primary", "family"])
        self.assertEqual([(e["title"], e["calendar"]) for e in got],
                         [("dinner", "primary"), ("mine", "primary")])  # fmt: skip
        self.assertEqual([a[0] for a in asked], ["id-primary", "id-family"])
        self.assertEqual(asked[0][2] - asked[0][1], timedelta(days=1))


class GoogleEventsTest(unittest.TestCase):
    def test_no_robot_may_read_events(self):
        for robot in ("rush", "roll", "training"):
            with self.assertRaises(PermissionError):
                google.EventCalendar(robot, "a@b.c")

    def test_dash_asks_only_for_read_scopes(self):
        self.assertEqual(google.EVENT_READERS, {"dash"})
        for scope in google.SCOPES["dash"]:
            self.assertTrue(scope.endswith(".readonly"), scope)

    def test_events_pages_and_escapes_the_calendar_id(self):
        urls = []

        class Response:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(self.body).encode()

        def opener(req, timeout=None):
            if not hasattr(req, "full_url"):
                return Response({"access_token": "t"})
            urls.append(req.full_url)
            first = "pageToken" not in req.full_url
            return Response({"items": [{"id": "1" if first else "2"}],
                             **({"nextPageToken": "p2"} if first else {})})  # fmt: skip

        def get(service):
            if service == google.CLIENT_KEYCHAIN:
                return json.dumps({"installed": {"client_id": "c", "client_secret": "s"}})
            return json.dumps({"refresh_token": "r"})

        with mock.patch.object(google, "_post", return_value={"access_token": "t"}):
            cal = google.EventCalendar("dash", "a@b.c", get=get, opener=opener)
            got = cal.events("fam#ily@group", NOW, NOW + timedelta(days=1))
        self.assertEqual([e["id"] for e in got], ["1", "2"])
        self.assertIn("/calendars/fam%23ily%40group/events?", urls[0])
        self.assertIn("singleEvents=true", urls[0])


class DecoderTest(unittest.TestCase):
    def test_plain_keys_in_order(self):
        self.assertEqual(app.Decoder().feed(b"xa1"), ["x", "a", "1"])

    def test_an_arrow_key_is_one_sequence_never_a_quit(self):
        d = app.Decoder()
        self.assertEqual(d.feed(b"\x1b[A\x1bOB\x1b[1;5Cq"), ["seq", "seq", "seq", "q"])

    def test_a_sequence_split_across_reads(self):
        d = app.Decoder()
        self.assertEqual(d.feed(b"\x1b"), [])
        self.assertEqual(d.feed(b"[A"), ["seq"])
        self.assertEqual(d.feed(b"\x1b["), [])
        self.assertEqual(d.feed(b"1;5"), [])
        self.assertEqual(d.feed(b"Dr"), ["seq", "r"])

    def test_a_slow_sequence_is_never_read_as_keys(self):
        # A pause mid-sequence (ssh, a loaded machine): the tail must not become keys.
        d = app.Decoder()
        self.assertEqual(d.feed(b"\x1b["), [])
        self.assertEqual(d.flush(), [])
        self.assertEqual(d.feed(b"3~q"), ["seq", "q"])  # Delete, not "open row 3"
        self.assertEqual(d.feed(b"\x1b[20"), [])
        self.assertEqual(d.flush(), [])
        self.assertEqual(d.feed(b"0~xaq"), [])  # a paste began: nothing acts
        self.assertEqual(d.feed(b"\x1b"), [])
        self.assertEqual(d.flush(), [])  # ESC inside a paste waits for its sequence
        self.assertFalse(d.lone_esc)
        self.assertEqual(d.feed(b"[201~r"), ["r"])

    def test_esc_alone_becomes_esc_only_after_a_pause(self):
        d = app.Decoder()
        self.assertEqual(d.feed(b"\x1b"), [])
        self.assertEqual(d.flush(), ["esc"])
        self.assertEqual(d.flush(), [])

    def test_pasted_text_is_dropped_whole(self):
        d = app.Decoder()
        self.assertEqual(d.feed(b"r\x1b[200~quit x a"), ["r"])
        self.assertEqual(d.feed(b"q q\x1b[201~u"), ["u"])

    def test_utf8_and_control_bytes_are_other(self):
        self.assertEqual(app.Decoder().feed("é\n🙂q".encode()), ["other", "other", "other", "q"])


class FeedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.var = Path(self.tmp.name)
        self.since = NOW - timedelta(days=1)

    def journal(self, robot, *lines):
        (self.var / robot).mkdir(exist_ok=True)
        (self.var / robot / "journal.md").write_text("".join(f"- {line}\n" for line in lines))

    def test_journal_lines_are_events_without_the_routine_ones(self):
        self.journal(
            "rush",
            "2026-11-20T10:00:00+00:00 sent aaaa1111 (comment) from the remote",  # too old
            "2026-11-24T12:00:00+00:00 tick: 0 draft(s)",
            "2026-11-24T12:01:00+00:00 mail: 1 receipt",
            "2026-11-24T12:02:00+00:00 texted PJ about GitHub: 1 update(s)",
            "2026-11-24T12:03:00+00:00 texted PJ about 08c5c57a",
            "2026-11-24T12:04:00+00:00 a5e227c7 superseded by 40e4c1fe",
            "not a journal line",
            "2026-11-24T12:05:00+00:00 tick: 2 draft(s)",
            "2026-11-24T12:06:00+00:00 mail check failed for a@b.c: HTTP Error 500",
            "2026-11-24T12:07:00+00:00 GitHub: CI failed on pj/x main (CI): https://gh/1",
            "2026-11-24T12:08:00+00:00 GitHub: CI passing again on pj/x main (CI)",
            "2026-11-24T12:09:00+00:00 GitHub: CI failed on pj/x main (Python next): u",
        )
        found = feed.journal("rush", self.since, self.var)
        self.assertEqual(
            [(e["text"], e["level"]) for e in reversed(found)],
            [("tick: 2 draft(s)", ""),
             ("mail check failed for a@b.c: HTTP Error 500", "bad"),
             ("CI failed on pj/x main (CI): https://gh/1", "bad"),
             ("CI passing again on pj/x main (CI)", "good"),
             ("CI failed on pj/x main (Python next): u", "")],
        )  # fmt: skip
        self.assertEqual(found[0]["at"], datetime(2026, 11, 24, 12, 9, tzinfo=UTC))
        self.assertEqual(feed.journal("roll", self.since, self.var), [])

    def test_failed_dagster_runs_and_finished_evals_are_events(self):
        db = self.var / "runs.db"
        with closing(sqlite3.connect(db)) as con:
            con.execute("CREATE TABLE runs (pipeline_name, status, start_time, end_time)")
            at = (NOW - timedelta(hours=2)).timestamp()
            con.executemany("INSERT INTO runs VALUES (?, ?, ?, ?)", [
                ("queue_job", "SUCCESS", at, at),
                ("claude_job", "FAILURE", at, at),
                ("old_job", "FAILURE", at - 5 * 86400, at - 5 * 86400),
            ])  # fmt: skip
            con.commit()
        self.assertEqual(
            [(e["source"], e["text"], e["level"]) for e in feed.dagster(self.since, db)],
            [("dagster", "claude_job failure", "bad")],
        )
        (self.var / "evals").mkdir()
        for name, ended, status in (("a", "2026-11-24T09:00:00Z", "completed"),
                                    ("b", "2026-11-24T09:30:00Z", "cancelled"),
                                    ("c", "2026-11-01T09:00:00Z", "completed")):  # fmt: skip
            (self.var / "evals" / f"{name}.run.json").write_text(json.dumps(
                {"stage": name, "status": status, "ended_at": ended, "passed": 9, "done": 10}))  # fmt: skip
        (self.var / "evals" / "bad.run.json").write_text("{")
        self.assertEqual(
            sorted((e["text"], e["level"]) for e in feed.evals(self.since, self.var)),
            [("a completed 9/10", ""), ("b cancelled 9/10", "bad")],
        )

    def test_a_sessions_last_turn_is_an_event(self):
        project = self.var / "projects" / "p"
        project.mkdir(parents=True)
        log = project / "abc.jsonl"
        log.write_text("\n".join(json.dumps(r) for r in (
            {"type": "ai-title", "aiTitle": "fix the build"},
            {"type": "assistant", "timestamp": "2026-11-24T08:00:00Z", "message": {}},
            {"type": "assistant", "timestamp": "2026-11-24T09:00:00.500Z", "message": {}},
            {"type": "user", "timestamp": "2026-11-24T09:30:00Z"},
        )) + "\n")  # fmt: skip
        stamp = NOW.timestamp()
        os.utime(log, (stamp, stamp))
        found = feed.claude(self.since, self.var / "projects", now=NOW)
        self.assertEqual([(e["source"], e["text"]) for e in found],
                         [("claude", "fix the build: turn ended")])  # fmt: skip
        self.assertEqual(found[0]["at"].hour, 9)
        old = NOW - timedelta(days=30)
        os.utime(log, (old.timestamp(), old.timestamp()))
        self.assertEqual(feed.claude(self.since, self.var / "projects", now=NOW), [])

    def test_a_burst_is_one_line_with_a_count(self):
        def at(minute, text, source="rush"):
            return {"at": NOW - timedelta(minutes=minute), "source": source, "text": text,
                    "level": "bad"}  # fmt: skip

        found = feed.merged([
            at(1, "GitHub check failed for pj/a: timeout"),
            at(2, "GitHub check failed for pj/b: timeout"),
            at(3, "GitHub check failed for pj/c: timeout"),
            at(3, "GitHub check failed for pj/d: timeout", "roll"),
            at(30, "GitHub check failed for pj/e: timeout"),
        ])  # fmt: skip
        self.assertEqual([e["text"] for e in found], [
            "(3x) GitHub check failed for pj/a: timeout",
            "GitHub check failed for pj/d: timeout",
            "GitHub check failed for pj/e: timeout",
        ])  # fmt: skip

    def test_a_time_span(self):
        self.assertEqual(feed.span("6h"), timedelta(hours=6))
        self.assertEqual(feed.span(" 2D "), timedelta(days=2))
        for bad in ("", "0d", "soon", "3y"):
            with self.assertRaises(ValueError):
                feed.span(bad)

    def test_lab_feed_prints_oldest_first_and_only_new_lines_after(self):
        import io

        first = {"at": NOW - timedelta(hours=2), "source": "rush", "text": "one", "level": ""}
        second = {
            "at": NOW - timedelta(hours=1),
            "source": "roll",
            "text": "two\x1b[2J",
            "level": "bad",
        }
        answers = iter([[second, first], [second, first], KeyboardInterrupt()])

        def events(since):
            answer = next(answers)
            if isinstance(answer, BaseException):
                raise answer
            return answer

        out = io.StringIO()
        with mock.patch.object(feed, "events", events):
            app.follow("1d", out=out, sleep=lambda s: None)
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].endswith("rush     one"))
        self.assertTrue(lines[1].endswith("roll     two[2J"))


class PressTest(unittest.TestCase):
    def test_f_opens_and_closes_the_feed(self):
        state = app.State()
        self.assertEqual(app.press(state, "f"), [])
        self.assertTrue(state.feed_open)
        app.press(state, "f")
        self.assertFalse(state.feed_open)

    def test_j_opens_and_closes_the_job_list(self):
        state = app.State()
        self.assertEqual(app.press(state, "j"), [])
        self.assertTrue(state.jobs_open)
        app.press(state, "j")
        self.assertFalse(state.jobs_open)

    def state(self, text="- [ ] one\n- [ ] [[Ann]] two\n"):
        d, path = tasks_file(text)
        self.addCleanup(d.cleanup)
        snap = tasks.read(path)
        _, _, letters = app.assign_letters(snap)
        return app.State(snapshot=snap, letters=letters), path

    def test_keys_in_normal_mode(self):
        s, _ = self.state()
        self.assertEqual(app.press(s, "q"), [("quit",)])
        self.assertEqual(app.press(s, "r"), [("refresh",)])
        self.assertEqual(app.press(s, "R"), [("reload",)])
        self.assertEqual(app.press(s, "u"), [("undo",)])
        for key in ("esc", "seq", "other", "a", "Q", " "):
            self.assertEqual(app.press(s, key), [], key)
            self.assertEqual(s.mode, "normal")

    def test_x_then_a_letter_checks_that_task(self):
        s, _ = self.state()
        self.assertEqual(app.press(s, "x"), [])
        self.assertEqual(s.mode, "pick")
        (effect,) = app.press(s, "b")
        self.assertEqual((effect[0], effect[1].text, effect[1].who), ("check", "two", "Ann"))
        self.assertEqual(s.mode, "normal")

    def test_any_other_key_cancels_the_pick(self):
        for key in ("esc", "seq", "q", "z", "1", "A"):
            s, _ = self.state()
            app.press(s, "x")
            self.assertEqual(app.press(s, key), [], key)
            self.assertEqual(s.mode, "normal")

    def test_x_with_no_tasks_does_not_enter_pick(self):
        s, _ = self.state("nothing here\n")
        app.press(s, "x")
        self.assertEqual((s.mode, s.message), ("normal", "no open tasks"))

    def test_letters_stay_frozen_while_picking(self):
        s, path = self.state()
        sources = {k: app.Poller(lambda: None, 1) for k in ("events", "review", "models")}
        app.press(s, "x")
        path.write_text("- [ ] zero\n- [ ] one\n- [ ] [[Ann]] two\n")  # everything shifts
        with mock.patch.object(tasks, "path", return_value=path), self.quiet():
            app.gather(s, sources, NOW)
            self.assertEqual(s.letters["a"].text, "one")
            (effect,) = app.press(s, "a")
            app.do_check(s, effect[1])  # the file changed: refused, nothing written
            self.assertIn("not checked", s.message)
            self.assertNotIn("[x]", path.read_text())
            app.gather(s, sources, NOW)  # out of pick mode: the list is re-read
            self.assertEqual(s.letters["a"].text, "zero")

    def test_yesterdays_events_are_not_shown_as_todays(self):
        s, path = self.state()
        row = agenda.normalize(
            event("old", "2026-11-23T10:00:00-05:00", "2026-11-23T11:00:00-05:00"), "primary"
        )
        answers = iter([{"day": TODAY - timedelta(days=1), "events": [row]}])
        sources = {k: app.Poller(lambda: None, 1) for k in ("review", "models")}
        sources["events"] = app.Poller(lambda: next(answers), 1)
        sources["events"].once()
        with mock.patch.object(tasks, "path", return_value=path), self.quiet():
            model_ = app.gather(s, sources, NOW)
        self.assertIsNone(model_["events"])
        self.assertEqual(s.events, [])
        self.assertTrue(sources["events"]._wake.is_set())

    def quiet(self):
        """gather() with the lab's own readers stubbed out."""
        stack = mock.patch.multiple(
            labstate,
            agents=list,
            dagster_jobs=list,
            heavy_job=lambda now: None,
            training_today=lambda day: None,
            queue=lambda now: [],
            evals=list,
            dagster_heartbeat=lambda now: None,
            rush_tick=lambda now: None,
        )
        return _Both(stack, mock.patch.object(sessions, "live", return_value=[]))

    def test_check_then_undo_twice_in_order(self):
        s, path = self.state("- [ ] one\n- [ ] two\n")
        app.do_check(s, s.letters["a"])
        s.snapshot = tasks.read(path)
        _, _, s.letters = app.assign_letters(s.snapshot)
        app.do_check(s, s.letters["a"])  # "two" is now a
        self.assertEqual(path.read_text(), "- [x] one\n- [x] two\n")
        app.do_undo(s)
        app.do_undo(s)
        self.assertEqual(path.read_text(), "- [ ] one\n- [ ] two\n")
        app.do_undo(s)
        self.assertEqual(s.message, "nothing to undo")

    def test_undo_is_dropped_once_the_file_changes_underneath(self):
        s, path = self.state()
        app.do_check(s, s.letters["a"])
        path.write_text(path.read_text() + "- [ ] added by hand\n")
        os.utime(path, ns=(1, s.our_mtime + 1_000_000_000))
        app.do_undo(s)
        self.assertIn("not undone", s.message)
        self.assertEqual(s.undo, [])
        self.assertIn("- [x] one", path.read_text())

    def test_number_keys_act_on_the_rows_as_displayed(self):
        s, _ = self.state()
        s.events = [{"n": 1, "url": ""}, {"n": 2, "url": "https://meet.example/x"}]
        self.assertEqual(app.press(s, "2"), [("open", "https://meet.example/x")])
        self.assertEqual(app.press(s, "1"), [])
        self.assertEqual(s.message, "row 1 has no link")
        self.assertEqual(app.press(s, "3"), [])
        self.assertEqual(s.message, "no row 3")

    def test_only_https_is_opened(self):
        with mock.patch.object(app.subprocess, "Popen") as popen:
            app._open("file:///etc/passwd")
            app._open("http://plain.example")
            popen.assert_not_called()
            app._open("https://meet.example/x")
            self.assertEqual(popen.call_args.args[0], ["open", "https://meet.example/x"])

    def test_more_than_26_tasks_leaves_the_rest_unlettered(self):
        s, _ = self.state("".join(f"- [ ] task {i}\n" for i in range(30)))
        mine, _, letters = app.assign_letters(s.snapshot)
        self.assertEqual(len(letters), 26)
        self.assertEqual([letter for letter, _ in mine[25:28]], ["z", "", ""])


class _Both:
    def __init__(self, *patches):
        self.patches = patches

    def __enter__(self):
        for p in self.patches:
            p.start()

    def __exit__(self, *a):
        for p in self.patches:
            p.stop()


class PollerTest(unittest.TestCase):
    def test_a_failure_keeps_the_last_value_and_names_the_error(self):
        answers = iter([lambda: [1], lambda: 1 / 0])
        p = app.Poller(lambda: next(answers)(), 1)
        p.once()
        p.once()
        value, error, at = p.get()
        self.assertEqual(value, [1])
        self.assertIn("ZeroDivisionError", error)
        self.assertIsNotNone(at)

    def test_errors_never_carry_a_command_line(self):
        import subprocess

        gh = subprocess.CalledProcessError(1, ["gh", "search", "--token", "SECRET"])
        self.assertEqual(app.describe(gh), "gh failed (exit 1)")
        keychain = subprocess.CalledProcessError(44, ["security", "find-generic-password"])
        self.assertIn("lab google auth dash", app.describe(keychain))
        locked = subprocess.CalledProcessError(36, ["security", "find-generic-password"])
        self.assertEqual(app.describe(locked), "Keychain could not be read (security exit 36)")


class LabStateTest(unittest.TestCase):
    def test_launchd_rows(self):
        loaded = {
            "com.pjkelly.light-labs.dagster": (33933, 143),
            "com.pjkelly.light-labs.rush": (None, 1),
            "com.pjkelly.light-labs.brief": (None, 0),
            "com.pjkelly.light-labs.workouts": (None, -15),
            "com.pjkelly.relationship-radar.sync": (None, 0),
        }
        plists = {**dict.fromkeys(loaded, False), "com.pjkelly.light-labs.workouts": True,
                  "com.pjkelly.light-labs.ollama": True}  # fmt: skip
        rows = {r["name"]: (r["state"], r["ok"]) for r in labstate.agents(loaded, plists)}
        self.assertEqual(rows, {
            "dagster": ("running", True),
            "rush": ("last run failed (exit 1)", False),
            "brief": ("ok", True),
            "workouts": ("stopped", False),  # KeepAlive, but no process
            "ollama": ("not loaded", False),
            "relationship-radar.sync": ("ok", True),
        })  # fmt: skip

    def test_launchctl_output_is_parsed_and_filtered(self):
        out = "PID\tStatus\tLabel\n-\t0\tcom.apple.thing\n74\t0\tcom.pjkelly.light-labs.ollama\n"

        def run(*a, **kw):
            return mock.Mock(stdout=out)

        self.assertEqual(labstate.launchctl_list(run), {"com.pjkelly.light-labs.ollama": (74, 0)})

    def dagster_db(self, runs, beats):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        db = Path(d.name) / "runs.db"
        with closing(sqlite3.connect(db)) as con, con:
            con.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, pipeline_name, status,"
                        " start_time, end_time)")  # fmt: skip
            con.execute("CREATE TABLE daemon_heartbeats (daemon_type, timestamp)")
            con.executemany("INSERT INTO runs (pipeline_name, status, start_time, end_time)"
                            " VALUES (?, ?, ?, ?)", runs)  # fmt: skip
            con.executemany("INSERT INTO daemon_heartbeats VALUES (?, ?)", beats)
        return db

    def test_the_latest_run_of_each_dagster_job(self):
        db = self.dagster_db(
            [("a_job", "FAILURE", 1.0, 2.0), ("a_job", "SUCCESS", 3.0, 4.0),
             ("b_job", "SUCCESS", 1.0, 2.0), ("b_job", "FAILURE", 5.0, 6.0),
             ("c_job", "STARTED", 7.0, None)], [],
        )  # fmt: skip
        rows = {j["name"]: (j["status"], j["ok"]) for j in labstate.dagster_jobs(db)}
        self.assertEqual(rows, {"a_job": ("SUCCESS", True), "b_job": ("FAILURE", False),
                                "c_job": ("STARTED", True)})  # fmt: skip
        self.assertEqual(labstate.dagster_jobs(Path(db.parent / "none.db")), [])

    def test_a_stopped_daemon_is_a_problem(self):
        now = datetime(2026, 11, 24, 21, 0, tzinfo=UTC)
        fresh, stale = "2026-11-24 20:59:30.5", "2026-11-24 20:40:00.0"
        ok = self.dagster_db([], [("SCHEDULER", fresh), ("SENSOR", fresh)])
        self.assertIsNone(labstate.dagster_heartbeat(now, ok))
        bad = self.dagster_db([], [("SCHEDULER", fresh), ("SENSOR", stale)])
        self.assertIn("no sensor heartbeat since Tue 15:40", labstate.dagster_heartbeat(now, bad))
        none = self.dagster_db([], [("SENSOR", fresh)])
        self.assertIn("no scheduler heartbeat", labstate.dagster_heartbeat(now, none))

    def test_the_heavy_lock_is_read_and_never_removed(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        lock = Path(d.name) / "heavy.lock"
        started = (NOW - timedelta(minutes=12)).isoformat()
        lock.write_text(json.dumps({"pid": os.getpid(), "job": "fight", "started_at": started}))
        self.assertEqual(labstate.heavy_job(NOW, lock), "heavy job: fight, 12m")
        lock.write_text(json.dumps({"pid": 2**22 + 12345, "job": "fight", "started_at": started}))
        self.assertIsNone(labstate.heavy_job(NOW, lock))
        self.assertTrue(lock.exists())  # a dead holder's lock is the next job's to clear
        lock.write_text("[]")
        self.assertIsNone(labstate.heavy_job(NOW, lock))

    def test_a_queue_item_with_the_wrong_types_still_draws(self):
        rows = labstate.queue(NOW, [{"robot": None, "kind": 5, "created": 7}], Path("/nonexistent"))
        self.assertEqual([(r["robot"], r["kind"], r["count"]) for r in rows], [("?", "5", 1)])
        self.assertIn(
            "?  5  1 waiting", "\n".join(render.frame(model(queue=rows), 100, color=False))
        )

    def test_queue_groups_by_robot_and_kind(self):
        pending = [
            {"robot": "rush", "kind": "comment", "escalated": True,
             "created": "2026-11-20T10:00:00+00:00"},
            {"robot": "rush", "kind": "comment", "escalated": False,
             "created": "2026-11-01T10:00:00+00:00"},
            {"robot": "roll", "kind": "dependabot", "escalated": True, "created": None},
        ]  # fmt: skip
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        asks = Path(d.name) / "asks.jsonl"
        asks.write_text('{"id": "a", "outcome": "held"}\n{"id": "b", "outcome": "held"}\n'
                        '{"id": "b", "outcome": "noted"}\nnot json\n')  # fmt: skip
        rows = labstate.queue(NOW, pending, asks)
        self.assertEqual([(r["robot"], r["kind"], r["count"], r["escalated"]) for r in rows],
                         [("rush", "comment", 2, 1), ("roll", "dependabot", 1, 1),
                          ("rush", "held ask", 1, 0)])  # fmt: skip
        self.assertEqual(rows[0]["oldest"].day, 1)

    def test_rush_tick_and_training_and_evals_read_var(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        var = Path(d.name)
        (var / "rush").mkdir()
        (var / "training" / "plans").mkdir(parents=True)
        (var / "evals").mkdir()
        state = var / "rush" / "state.json"
        state.write_text(json.dumps({"updated_at": "2026-11-24T14:55:00+00:00"}))
        self.assertIsNone(labstate.rush_tick(NOW, state))
        late = NOW + timedelta(hours=2)
        self.assertEqual(labstate.rush_tick(late, state), "Rush: no tick since Tue 09:55")
        plan = {"days": [{"date": "2026-11-24", "rest": False, "slot": ["06:30", "07:15"],
                          "type": "lift", "title": "Mix 3A", "items": [{}, {}]}]}  # fmt: skip
        (var / "training" / "plans" / "2026-W48.json").write_text(json.dumps(plan))
        (var / "training" / "plans" / "2026-W49.json").write_text("{broken")
        self.assertEqual(
            labstate.training_today(TODAY, var),
            {"rest": False, "title": "Mix 3A", "type": "lift", "slot": "06:30-07:15", "items": 2},
        )
        self.assertIsNone(labstate.training_today(TODAY + timedelta(days=1), var))
        for run_id, started, passed in (("a", "2026-10-01T00:00:00Z", 1),
                                        ("b", "2026-10-02T00:00:00.5Z", 2)):  # fmt: skip
            (var / "evals" / f"{run_id}.run.json").write_text(json.dumps(
                {"stage": "mail-keep", "started_at": started, "passed": passed, "done": 3,
                 "total": 3, "status": "completed"}))  # fmt: skip
        (var / "evals" / "c.run.json").write_text("[]")
        self.assertEqual([(r["stage"], r["passed"]) for r in labstate.evals(var)],
                         [("mail-keep", 2)])  # fmt: skip


class ReviewTest(unittest.TestCase):
    def test_rows_cover_only_watched_repos_and_skip_bots_and_drafts(self):
        status = {
            "ci_failing": {"kellypj24/scouter": ["CI"], "kellypj24/other": ["CI"]},
            "open_prs": [
                {"repo": "kellypj24/recoup", "number": 5, "title": "red", "url": "u5",
                 "draft": False, "review": None, "checks_failing": 2},
                {"repo": "kellypj24/recoup", "number": 6, "title": "green", "url": "u6",
                 "draft": False, "review": None, "checks_failing": 0},
                {"repo": "kellypj24/recoup", "number": 7, "title": "draft", "url": "u7",
                 "draft": True, "review": None, "checks_failing": 1},
                {"repo": "kellypj24/other", "number": 8, "title": "elsewhere", "url": "u8",
                 "draft": False, "review": None, "checks_failing": 1},
            ],
        }  # fmt: skip
        asked = [
            {"repository": {"nameWithOwner": "kellypj24/scouter"}, "number": 9, "title": "t",
             "url": "u9", "author": {"login": "ketan"}},
            {"repository": {"nameWithOwner": "kellypj24/scouter"}, "number": 10, "title": "bump",
             "url": "u10", "author": {"login": "app/dependabot", "is_bot": True}},
        ]  # fmt: skip
        issues = [{"repository": {"nameWithOwner": "kellypj24/recoup"}, "number": 11,
                   "title": "fix  the\nthing", "url": "u11", "author": {"login": "pj"}}]  # fmt: skip

        def gh(*args, **kw):
            return asked if "prs" in args else issues

        watched = {"kellypj24/scouter", "kellypj24/recoup"}
        with mock.patch.object(review.mcp_server, "github_status", return_value=status), \
                mock.patch.object(review.mcp_server, "_gh", gh):  # fmt: skip
            rows = review.fetch(watched=watched)
        self.assertEqual(
            [(r["kind"], r["repo"], r["number"], r["detail"]) for r in rows],
            [("ci", "scouter", None, "CI"), ("pr", "recoup", 5, "2 failing"),
             ("review", "scouter", 9, "review requested"), ("issue", "recoup", 11, "")],
        )  # fmt: skip
        self.assertEqual(rows[-1]["title"], "fix the thing")

    def test_a_failing_canary_is_its_own_row_after_everything_else(self):
        status = {"open_prs": [], "ci_failing": {
            "kellypj24/scouter": ["Python next"],
            "kellypj24/recoup": ["CI", "python next"],
        }}  # fmt: skip
        watched = {"kellypj24/scouter", "kellypj24/recoup"}
        with mock.patch.object(review.mcp_server, "github_status", return_value=status), \
                mock.patch.object(review.mcp_server, "_gh", lambda *a, **kw: []):  # fmt: skip
            rows = review.fetch(watched=watched)
            with mock.patch.dict(os.environ, {"DASH_CANARIES": "nightly"}):
                strict = review.fetch(watched=watched)
        self.assertEqual(
            [(r["kind"], r["repo"], r["title"], r["detail"]) for r in rows],
            [("ci", "recoup", "main is red", "CI"),
             ("canary", "recoup", "python next is failing", ""),
             ("canary", "scouter", "Python next is failing", "")],
        )  # fmt: skip
        self.assertEqual([r["kind"] for r in strict], ["ci", "ci"])

    def test_repo_names_default_to_pjs_account(self):
        with mock.patch.dict(os.environ, {"DASH_REPOS": "scouter, someone/else"}):
            self.assertEqual(review.repos(), {"kellypj24/scouter", "someone/else"})


def model(**over):
    snap = tasks.Snapshot(Path("/tmp/tasks.md"), 1, (
        tasks.Task(0, "", "renew registration", None, TODAY - timedelta(days=1)),
        tasks.Task(1, "", "send key", "Ketan", None),
    ))  # fmt: skip
    mine, waiting, _ = app.assign_letters(snap)
    base = {
        "now": NOW, "mode": "normal", "message": "", "notes": [], "problems": [],
        "sessions": [{"pid": 1, "name": "n", "title": "fix the build", "cwd": "repo",
                      "status": "idle", "waiting": True, "since": NOW - timedelta(minutes=12),
                      "context": 163000, "reply": "Done. Which branch?"}],
        "events": agenda.rows([agenda.normalize(
            event("standup", "2026-11-24T10:25:00-05:00", "2026-11-24T10:40:00-05:00",
                  hangoutLink="https://meet.google.com/a"), "primary")], NOW),
        "events_error": "", "training": None, "queue": [], "queue_error": "",
        "tasks_mine": mine, "tasks_waiting": waiting, "tasks_note": "~/tasks/tasks.md",
        "review": [], "review_error": "", "review_at": NOW - timedelta(minutes=3),
        "agents": [{"name": f"job{i}", "state": "ok", "ok": True} for i in range(8)],
        "jobs": [{"name": "a_job", "status": "SUCCESS", "at": NOW, "ok": True}],
        "evals": [],
    }  # fmt: skip
    return {**base, **over}


class RenderTest(unittest.TestCase):
    def text(self, **kw):
        return "\n".join(render.frame(model(**kw), 100, color=False))

    def test_a_frame_has_every_section(self):
        text = self.text()
        for want in ("CLAUDE SESSIONS  1 waiting on you, 1 live", "your turn  12m", "163k",
                     "▸  1  10:25-10:40  in 25m  standup", "join primary",
                     "a  Mon 23 Nov  renew registration", "b  Ketan", "send key",
                     "REPO REVIEW QUEUE  fetched 3m ago", "clear",
                     "JOBS  launchd 8/8 ok · dagster 1/1 ok"):  # fmt: skip
            self.assertIn(want, text)
        self.assertNotIn("\033", text)

    def test_problems_and_messages_sit_under_the_header(self):
        lines = render.frame(model(problems=["rush: stopped", "calendar: expired"],
                                   message="checked: x"), 100, color=False)  # fmt: skip
        self.assertEqual(lines[1], "! rush: stopped · calendar: expired")
        self.assertEqual(lines[2], "checked: x")

    def test_wrap_breaks_at_spaces_and_marks_what_is_left(self):
        self.assertEqual(render.wrap("one two three", 20, 2), ["one two three"])
        self.assertEqual(render.wrap("one two three four", 9, 3), ["one two", "three", "four"])
        self.assertEqual(render.wrap("one two three four", 9, 2), ["one two", "three fo…"])
        self.assertEqual(render.wrap("abcdefghij kl", 4, 3), ["abcd", "efgh", "ij …"])
        self.assertEqual(render.wrap("日本語 テスト", 6, 2), ["日本語", "テスト"])
        self.assertEqual(render.wrap("one two", 4, 1), ["one…"])

    def test_a_long_cell_wraps_under_its_own_column(self):
        rows = [["a", ("Mon", "dim"), "pay the water bill before the end of the month"]]
        lines = render.table(rows, 30, render.Paint(False), flex=2, wrap_to=3)
        self.assertEqual(lines, ["  a  Mon  pay the water bill",
                                 "          before the end of",
                                 "          the month"])  # fmt: skip
        self.assertTrue(all(render.width(line) <= 30 for line in lines))

    def test_a_session_reply_sits_under_its_row_as_plain_prose(self):
        sessions_ = model()["sessions"]
        sessions_[0]["reply"] = (
            "**Done.** See [PR #9](https://example.com/9) and `just check`.\n- one"
        )
        lines = render.frame(model(sessions=sessions_), 100, color=False)
        row = next(i for i, line in enumerate(lines) if "your turn" in line)
        self.assertEqual(lines[row + 1], "    Done. See PR #9 and just check. one")

    def test_jobs_fill_as_many_columns_as_fit(self):
        items = [(f"job{i}", "ok", True) for i in range(5)] + [("long-name", "stopped", False)]
        paint = render.Paint(False)
        wide = render.grid("launchd", items, 100, paint)
        want = "  launchd  job0  ok    job1  ok    job2  ok    job3  ok    job4  ok    long-name  stopped"
        self.assertEqual(wide, [want])
        narrow = render.grid("launchd", items, 44, paint)
        self.assertEqual(narrow, ["  launchd  job0  ok    job3       ok",
                                  "           job1  ok    job4       ok",
                                  "           job2  ok    long-name  stopped"])  # fmt: skip
        self.assertEqual(len(render.grid("launchd", items, 10, paint)), 6)

    def test_a_narrow_window_puts_the_key_hints_on_their_own_line(self):
        lines = render.frame(model(), 60, color=False)
        self.assertTrue(lines[0].startswith("lab dash"))
        self.assertIn("r refresh", lines[1])
        self.assertTrue(all(render.width(line) <= 60 for line in lines))

    def test_control_characters_from_outside_never_reach_the_terminal(self):
        evil = "\x1b[2J\x1b]0;owned\x07title\u202e\r\nnext"
        sessions_ = model()["sessions"]
        sessions_[0].update(title=evil, reply=evil)
        runs = [{"stage": evil, "at": NOW, "status": evil, "passed": 1, "done": 2, "total": 2}]
        queue = [{"robot": evil, "kind": evil, "count": 1, "escalated": 0, "oldest": None}]
        text = "\n".join(render.frame(
            model(sessions=sessions_, problems=[evil], evals=runs, queue=queue, notes=[evil],
                  message=evil, tasks_note=evil, events_error=evil, review_error=evil), 100))  # fmt: skip
        stripped = text.replace("\033[0m", "")
        for code in ("\x1b[2J", "\x1b]", "\x07", "\u202e", "\r"):
            self.assertNotIn(code, stripped)

    def test_every_line_fits_the_width(self):
        long = "wide 🙂 title " * 30
        review_rows = [{"kind": "pr", "repo": "recoup", "number": 5, "title": long,
                        "detail": "2 failing", "url": ""}]  # fmt: skip
        for cols in (60, 100):
            for line in render.frame(model(review=review_rows, problems=[long]), cols, color=False):
                self.assertLessEqual(render.width(line), cols, line)

    def test_jobs_are_a_count_until_opened_and_failures_are_always_listed(self):
        self.assertNotIn("job0", self.text())
        self.assertIn("  launchd  job0", self.text(jobs_open=True))
        agents = model()["agents"]
        agents[2].update(state="stopped", ok=False)
        text = self.text(agents=agents)
        self.assertIn("JOBS  launchd 7/8 ok · dagster 1/1 ok\n  job2  stopped", text)
        self.assertNotIn("job0", text)

    def test_a_side_pane_wraps_the_key_hints_and_drops_the_folder(self):
        lines = render.frame(model(), 60, color=False)
        self.assertEqual(lines[1], "r refresh  1-9 open  x check  u undo  j jobs  f feed  q quit")
        narrow = render.frame(model(), 40, color=False)
        self.assertEqual(
            narrow[1:3], ["r refresh  1-9 open  x check  u undo", "j jobs  f feed  q quit"]
        )
        self.assertIn("fix the build  repo  163k", self.text())
        self.assertIn("fix the build  163k", "\n".join(lines))

    def test_recent_shows_the_last_four_events_and_f_shows_the_feed_alone(self):
        found = [{"at": NOW - timedelta(minutes=10 * i + 5), "source": "rush",
                  "text": f"event {i}", "level": "bad" if i == 0 else ""} for i in range(6)]  # fmt: skip
        self.assertNotIn("RECENT", self.text())
        text = self.text(feed=found)
        self.assertIn("RECENT  f for more\n  5m   rush  event 0\n  15m  rush  event 1", text)
        self.assertIn("event 3", text)
        self.assertNotIn("event 4", text)
        opened = render.frame(model(feed=found, feed_open=True), 100, rows=20, color=False)
        self.assertIn("FEED  last 7 days · f to close", opened)
        self.assertIn("  55m  rush  event 5", opened)
        self.assertNotIn("TASKS", "\n".join(opened))
        self.assertLessEqual(len(render.frame(model(feed=found, feed_open=True), 100, rows=6)), 6)

    def test_a_short_window_is_cut_with_a_count(self):
        cut = render.frame(model(), 100, rows=6, color=False)
        self.assertEqual(len(cut), 6)
        self.assertIn("more lines", cut[-1])

    def test_pick_mode_changes_the_hint(self):
        self.assertIn("letter: check off", self.text(mode="pick"))

    def test_an_emoji_presentation_character_is_two_columns(self):
        # Checked against literal column counts, not against render.width alone.
        self.assertEqual(render.width("\u2600\ufe0f"), 2)  # sun + VS16
        self.assertEqual(render.width("e\u0301"), 1)  # e + combining acute
        self.assertEqual(render.clip("\u2600\ufe0f\u2600\ufe0fab", 4), "\u2600\ufe0f…")
        line = render.clip_line("ab\u2600\ufe0fcd", 3)
        self.assertEqual(line, "ab")  # the sun needs columns 3-4

    def test_clip_counts_wide_characters(self):
        self.assertEqual(render.clip("日本語テキスト", 7), "日本語…")
        self.assertEqual(render.width(render.clip("日本語テキスト", 7)), 7)
        self.assertEqual(render.clip("abc", 3), "abc")


if __name__ == "__main__":
    unittest.main()
