import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from subprocess import CompletedProcess

from light_labs.agents.rush.phone import (
    PREFIX,
    notify_pending,
    ping,
    quiet,
    schedule_wake,
    text_for,
    wait_for_edge,
)
from light_labs.core.store import Store

NOW = datetime(2026, 10, 17, 15, 0, 0)


class Runner:
    """Stands in for subprocess.run: answers `pmset -g sched`, records everything."""

    def __init__(self, sched="", sudo_rc=0):
        self.sched, self.sudo_rc, self.calls = sched, sudo_rc, []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if cmd[:2] == ["pmset", "-g"]:
            return CompletedProcess(cmd, 0, stdout=self.sched, stderr="")
        return CompletedProcess(cmd, self.sudo_rc, stdout="", stderr="sudo: a password is required")


class TextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.sent = []

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, to, text):
        self.sent.append((to, text))

    def test_one_new_draft_is_texted_once_with_its_link(self):
        a = self.store.enqueue("comment", {"task_id": "t1"}, "Thanks!", "muse: nice work")
        self.assertEqual(notify_pending(self.store, "me", "http://mac/", self.send), [a["id"]])
        self.assertEqual(notify_pending(self.store, "me", "http://mac/", self.send), [])
        [(to, text)] = self.sent
        self.assertEqual(to, "me")
        self.assertTrue(text.startswith(f"{PREFIX} muse on t1, waiting for approval."))
        self.assertTrue(text.endswith(f"http://mac/#{a['id']}"))

    def test_escalations_say_they_need_pj(self):
        item = self.store.enqueue(
            "reply", {"to": ["devin"]}, "On it.", "devin: x", escalate="run X"
        )
        self.assertIn("devin on inbox, needs you (run X).", text_for(item))

    def test_long_drafts_are_clipped_and_link_is_optional(self):
        item = self.store.enqueue("comment", {"task_id": "t1"}, "x" * 1000, "muse: hi")
        text = text_for(item)
        self.assertIn("x" * 300 + "…", text)
        self.assertNotIn("http", text)

    def test_several_new_drafts_become_one_digest(self):
        for n in range(7):
            self.store.enqueue("comment", {"task_id": f"t{n}"}, "d", f"agent{n}: hi")
        self.assertEqual(len(notify_pending(self.store, "me", "http://mac", self.send)), 7)
        self.assertEqual(len(self.sent), 1)
        text = self.sent[0][1]
        self.assertTrue(text.startswith(f"{PREFIX} 7 drafts waiting."))
        self.assertIn("- and 2 more", text)
        self.assertTrue(text.endswith("http://mac/"))

    def test_quiet_hours_hold_texts_until_morning(self):
        self.store.enqueue("comment", {"task_id": "t1"}, "d", "muse: hi")
        night, morning = datetime(2026, 10, 17, 2, 30), datetime(2026, 10, 17, 8, 0)
        self.assertEqual(
            notify_pending(self.store, "me", send=self.send, quiet_hours="0-8", now=night), []
        )
        self.assertEqual(self.sent, [])
        self.assertEqual(
            len(notify_pending(self.store, "me", send=self.send, quiet_hours="0-8", now=morning)), 1
        )

    def test_quiet_hours_can_wrap_midnight(self):
        self.assertTrue(quiet("22-7", datetime(2026, 1, 1, 23)))
        self.assertTrue(quiet("22-7", datetime(2026, 1, 1, 6)))
        self.assertFalse(quiet("22-7", datetime(2026, 1, 1, 12)))
        self.assertFalse(quiet("", datetime(2026, 1, 1, 3)))


class PingTest(unittest.TestCase):
    def test_pings_until_the_cutoff_and_not_in_quiet_hours(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, sent = Store(Path(tmp)), []

            def send(to, text):
                sent.append(text)

            until = "2026-10-17T23:59"
            self.assertTrue(
                ping(store, "me", until, True, send, "0-8", datetime(2026, 10, 17, 18, 5))
            )
            self.assertEqual(
                sent[0], f"{PREFIX} test ping 6:05 PM. Awake; board check ran; 0 drafts waiting."
            )
            self.assertFalse(
                ping(store, "me", until, True, send, "0-8", datetime(2026, 10, 18, 0, 5))
            )
            self.assertFalse(
                ping(store, "me", "", True, send, "0-8", datetime(2026, 10, 17, 18, 5))
            )
            self.assertEqual(len(sent), 1)


class WakeTest(unittest.TestCase):
    def test_wakes_land_on_the_top_of_the_hour(self):
        run = Runner()
        self.assertEqual(
            schedule_wake(60, run, datetime(2026, 10, 17, 15, 40, 12)), (True, "wake at 16:00")
        )
        self.assertEqual(
            schedule_wake(30, Runner(), datetime(2026, 10, 17, 15, 5)), (True, "wake at 15:30")
        )
        self.assertEqual(
            schedule_wake(60, Runner(), datetime(2026, 10, 17, 23, 0, 4)), (True, "wake at 00:00")
        )

    def test_schedules_without_prompting(self):
        run = Runner()
        schedule_wake(60, run, NOW)
        self.assertEqual(
            run.calls[-1],
            ["sudo", "-n", "/usr/bin/pmset", "schedule", "wake", "10/17/26 16:00:00"],
        )

    def test_skips_when_a_wake_is_already_due(self):
        run = Runner(
            sched="Scheduled power events:\n [0]  wake at 10/17/2026 15:40:00 by 'pmset'\n"
        )
        ok, detail = schedule_wake(60, run, NOW)
        self.assertTrue(ok)
        self.assertEqual(detail, "wake already due 15:40")
        self.assertEqual(len(run.calls), 1)

    def test_reports_a_missing_sudoers_line(self):
        ok, detail = schedule_wake(60, Runner(sudo_rc=1), NOW)
        self.assertFalse(ok)
        self.assertIn("password is required", detail)


class WaitForEdgeTest(unittest.TestCase):
    def test_waits_until_the_network_is_back(self):
        attempts = []

        def check():
            attempts.append(1)
            if len(attempts) < 3:
                raise OSError("no route")

        self.assertTrue(wait_for_edge(check, timeout=60, every=0, sleep=lambda s: None))
        self.assertEqual(len(attempts), 3)

    def test_gives_up(self):
        def check():
            raise OSError("no route")

        self.assertFalse(wait_for_edge(check, timeout=0, every=0, sleep=lambda s: None))


if __name__ == "__main__":
    unittest.main()
