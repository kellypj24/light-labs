import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from subprocess import CompletedProcess

from light_labs.agents.rush.phone import (
    PREFIX,
    notify_pending,
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

    def test_texts_each_waiting_draft_once(self):
        a = self.store.enqueue("comment", {"task_id": "t1"}, "Thanks!", "muse: nice work")
        b = self.store.enqueue(
            "reply", {"to": ["devin"]}, "On it.", "devin: run X", escalate="run X"
        )
        texted = notify_pending(self.store, "me", "http://mac/", self.send)
        self.assertCountEqual(texted, [a["id"], b["id"]])
        self.assertEqual(notify_pending(self.store, "me", "http://mac/", self.send), [])
        texts = {t.rsplit("#", 1)[1]: (to, t) for to, t in self.sent}
        to, text = texts[a["id"]]
        self.assertEqual(to, "me")
        self.assertTrue(text.startswith(f"{PREFIX} muse on t1, waiting for approval."))
        self.assertIn("needs you (run X)", texts[b["id"]][1])

    def test_long_drafts_are_clipped_and_link_is_optional(self):
        item = self.store.enqueue("comment", {"task_id": "t1"}, "x" * 1000, "muse: hi")
        text = text_for(item)
        self.assertIn("x" * 300 + "…", text)
        self.assertNotIn("http", text)


class WakeTest(unittest.TestCase):
    def test_schedules_an_hour_out_without_prompting(self):
        run = Runner()
        self.assertEqual(schedule_wake(60, run, NOW), (True, "wake at 16:00"))
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
