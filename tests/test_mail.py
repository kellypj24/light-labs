import json
import tempfile
import unittest
from pathlib import Path

from light_labs.agents.rush import mail
from light_labs.core.store import Store


class Brain:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def think(self, system, user, **kw):
        self.calls.append(user)
        return self.reply


def msg(**over):
    base = {"from": "Dana <dana@example.org>", "subject": "Thursday?", "snippet": "Free at 3?",
            "category": None, "unsubscribe": False}  # fmt: skip
    return {**base, **over}


class TriageTest(unittest.TestCase):
    def test_filed_bulk_mail_skips_the_model(self):
        brain = Brain("LABEL: needs_reply")
        out = mail.triage(brain, msg(category="promotions", unsubscribe=True, subject="Sale"))
        self.assertEqual((out["label"], out["by"], brain.calls), ("newsletter", "rule", []))

    def test_classify_then_summarize(self):
        class Two:
            def __init__(self):
                self.calls = []

            def think(self, system, user, **kw):
                self.calls.append((system, user))
                return "needs_reply" if len(self.calls) == 1 else "Dana asks about 3pm Thursday."

        brain = Two()
        out = mail.triage(brain, msg())
        self.assertEqual(
            (out["label"], out["summary"]), ("needs_reply", "Dana asks about 3pm Thursday.")
        )
        self.assertEqual(brain.calls[0][0], mail.CLASSIFY)
        self.assertIn("Unsubscribe header: no", brain.calls[0][1])
        self.assertIn("what the sender wants", brain.calls[1][0])

    def test_parse_tolerates_decoration_and_unknown_answers_are_unsorted(self):
        self.assertEqual(mail.parse_label("**Needs reply**"), "needs_reply")
        self.assertEqual(mail.parse_label("Label: spam."), "spam")
        self.assertIsNone(mail.parse_label("urgent"))
        self.assertEqual(mail.parse_summary('SUMMARY: "Order shipped."\nmore'), "Order shipped.")
        out = mail.triage(Brain("I think this is important."), msg())
        self.assertEqual((out["label"], out["by"]), ("unsorted", "model-unparsed"))


class FakeGmail:
    def __init__(self, ids):
        self.ids = ids

    def messages(self, query, max_results=50):
        return [{"id": i} for i in self.ids]

    def message(self, i):
        return {"id": i, "threadId": f"t{i}", "snippet": "hi", "labelIds": ["INBOX"],
                "payload": {"headers": [{"name": "From", "value": f"Person {i} <p{i}@x.org>"},
                                        {"name": "Subject", "value": f"Question {i}"}]}}  # fmt: skip


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.sent = []
        self.gmail = FakeGmail(["a"])
        self.brain = Brain("needs_reply")

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, quiet_hours=None):
        return mail.check(self.store, ["me@x"], self.brain, lambda a: self.gmail,
                          lambda to, t: self.sent.append(t), "chat", "http://mac", quiet_hours)  # fmt: skip

    def test_first_look_seeds_then_new_mail_is_triaged_once(self):
        self.assertEqual(self.run_check(), [])
        self.gmail.ids = ["b", "a"]
        [item] = self.run_check()
        self.assertEqual((item["id"], item["label"]), ("b", "needs_reply"))
        self.assertEqual(self.run_check(), [])
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Person b: needs_reply", self.sent[0])
        self.assertTrue(self.sent[0].endswith("http://mac/mail"))
        logged = (self.store.root / "mail" / "me@x.jsonl").read_text().splitlines()
        self.assertNotIn("snippet", json.loads(logged[0]))  # contents are not kept

    def test_quiet_hours_hold_the_text_until_after(self):
        self.run_check()
        self.gmail.ids = ["b", "a"]
        self.run_check(quiet_hours="0-24")  # always quiet
        self.assertEqual(self.sent, [])
        self.run_check()
        self.assertEqual(len(self.sent), 1)

    def test_a_failing_mailbox_is_journaled_not_raised(self):
        class Broken:
            def messages(self, *a, **k):
                raise OSError("token revoked")

        self.gmail = Broken()
        self.assertEqual(self.run_check(), [])
        self.assertIn("mail check failed for me@x", (self.store.root / "journal.md").read_text())

    def test_nothing_to_reply_to_sends_nothing(self):
        self.brain = Brain("receipt")
        self.run_check()
        self.gmail.ids = ["b", "a"]
        self.run_check()
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
