import io
import json
import tempfile
import unittest
from pathlib import Path

from light_labs.agents.roll import inbox

PJ = 42


class FakeGmail:
    account = "me@x"

    def __init__(self):
        self.relabels, self.queries = [], []

    def ids(self, query, cap=20000):
        self.queries.append(query)
        return ["m1", "m2"] if "promotions" in query else []

    def message(self, i, headers=()):
        return {"payload": {"headers": [{"name": "From", "value": "Deals <d@shop.example.com>"}]}}

    def call(self, path, **kw):
        return {"messagesTotal": 55030, "messagesUnread": 45422}

    def label_id(self, name):
        return f"L:{name}"

    def relabel(self, ids, add=(), remove=()):
        self.relabels.append((list(ids), list(add), list(remove)))


class Wire:
    def __init__(self):
        self.calls, self.updates = [], []

    def __call__(self, req, timeout=None):
        method = req.full_url.rsplit("/", 1)[1]
        self.calls.append((method, json.loads(req.data)))
        result = self.updates if method == "getUpdates" else {"message_id": len(self.calls)}
        if method == "getUpdates":
            self.updates = []
        return io.BytesIO(json.dumps({"ok": True, "result": result}).encode())


class RollInboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.gmail, self.wire = FakeGmail(), Wire()
        self.bot = inbox.RollBot("T", PJ, Path(self.tmp.name), self.gmail, opener=self.wire)

    def tearDown(self):
        self.tmp.cleanup()

    def press(self, data, chat=PJ):
        self.wire.updates = [{"update_id": 1, "callback_query": {
            "id": "q", "data": data, "message": {"message_id": 9, "chat": {"id": chat}, "text": "rule"}}}]  # fmt: skip
        self.bot.poll_once(None, timeout=0)

    def test_every_rule_spares_starred_mail(self):
        for rule_id in inbox.RULES:
            self.assertIn("-is:starred", inbox.search(rule_id))
            self.assertIn("older_than:", inbox.search(rule_id))

    def test_report_reads_only_and_offers_rules_with_matches(self):
        report = inbox.survey(self.gmail)
        self.assertEqual(self.gmail.relabels, [])
        self.assertEqual((report["inbox"], report["unread"]), (55030, 45422))
        promo = next(r for r in report["rules"] if r["id"] == "promotions-30d")
        self.assertEqual((promo["count"], promo["top"]), (2, [("Deals", 2)]))
        self.bot.send_report(report)
        buttons = [p["reply_markup"] for m, p in self.wire.calls if "reply_markup" in p]
        self.assertEqual(len(buttons), 1)  # only the rule that matched anything

    def test_approve_archives_and_undo_restores(self):
        self.press("apply:promotions-30d")
        self.assertEqual(self.gmail.relabels, [(["m1", "m2"], ["L:Roll/Promotions"], ["INBOX"])])
        self.assertEqual(self.bot.undo("promotions-30d"), 2)
        self.assertEqual(self.gmail.relabels[-1], (["m1", "m2"], ["INBOX"], ["L:Roll/Promotions"]))
        self.assertIsNone(self.bot.undo("promotions-30d"))  # already undone

    def test_skip_and_strangers_change_nothing(self):
        self.press("skip:promotions-30d")
        self.press("apply:promotions-30d", chat=7)
        self.press("apply:not-a-rule")
        self.assertEqual(self.gmail.relabels, [])


class LabelArchivedTest(RollInboxTest):
    def test_labels_mail_already_out_of_the_inbox(self):
        self.gmail.ids = lambda q, cap=0: self.gmail.queries.append(q) or ["old1"]
        self.assertEqual(self.bot.label_archived("promotions-30d"), 1)
        self.assertIn("-in:inbox -in:trash -in:spam", self.gmail.queries[-1])
        self.assertNotIn(" in:inbox", self.gmail.queries[-1])
        self.assertEqual(self.gmail.relabels[-1], (["old1"], ["L:Roll/Promotions"], []))

    def test_a_failing_update_is_reported_not_fatal(self):
        def boom(update, remote=None):
            raise ValueError("bad json")

        self.bot.handle = boom
        calls = []

        def stop(seconds):
            calls.append(seconds)
            raise KeyboardInterrupt

        self.wire.updates = [{"update_id": 1, "message": {"chat": {"id": PJ}, "text": "x"}}]
        with self.assertRaises(KeyboardInterrupt):
            self.bot.poll_forever(sleep=stop)
        self.assertIn("something failed", self.wire.calls[-1][1]["text"])

    def test_a_dropped_long_poll_retries_quietly(self):
        def drop(req, timeout=None):
            raise TimeoutError("The read operation timed out")

        self.bot.opener = drop
        with self.assertRaises(KeyboardInterrupt):
            self.bot.poll_forever(sleep=self._stop_after_one)
        self.assertEqual(self.wire.calls, [])  # nothing sent to PJ
        self.assertFalse((Path(self.tmp.name) / "journal.md").exists())

    def test_a_tap_that_fails_on_the_network_is_still_reported(self):
        def slow(query, cap=20000):
            raise TimeoutError("The read operation timed out")

        self.gmail.ids = slow
        self.press("apply:promotions-30d")
        self.assertIn(
            "something failed: The read operation timed out", self.wire.calls[-1][1]["text"]
        )
        journal = (Path(self.tmp.name) / "journal.md").read_text()
        self.assertIn("poll failed: The read operation timed out", journal)

    @staticmethod
    def _stop_after_one(seconds):
        raise KeyboardInterrupt


if __name__ == "__main__":
    unittest.main()
