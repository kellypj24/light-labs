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
        self.assertEqual(self.gmail.relabels, [(["m1", "m2"], [], ["INBOX"])])
        self.assertEqual(self.bot.undo("promotions-30d"), 2)
        self.assertEqual(self.gmail.relabels[-1], (["m1", "m2"], ["INBOX"], []))
        self.assertIsNone(self.bot.undo("promotions-30d"))  # already undone

    def test_skip_and_strangers_change_nothing(self):
        self.press("skip:promotions-30d")
        self.press("apply:promotions-30d", chat=7)
        self.press("apply:not-a-rule")
        self.assertEqual(self.gmail.relabels, [])


if __name__ == "__main__":
    unittest.main()
