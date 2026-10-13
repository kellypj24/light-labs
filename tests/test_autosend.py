import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from light_labs.agents.rush.autosend import Policy, guard
from light_labs.agents.rush.heartbeat import Heartbeat
from light_labs.core.store import Store
from tests.test_rush import FakeBrain, FakeClient, item

ON = {"enabled": True, "kinds": ["reply", "comment"], "daily_cap": 2, "per_thread": 1}
DM = {"to": ["nova"], "in_reply_to": "m1", "summary": "hi"}


class PostingClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.posted = []

    def send(self, actor, to, content, summary=None, in_reply_to=None):
        self.posted.append(("reply", to, content))
        return {"id": f"obj{len(self.posted)}"}

    def comment(self, actor, task_id, text):
        self.posted.append(("comment", task_id, text))
        return {"id": f"obj{len(self.posted)}"}


class GuardTest(unittest.TestCase):
    def test_plain_reply_passes(self):
        self.assertEqual(guard("Thanks, nova! Glad to be here.", "Welcome, Rush!"), [])

    def test_holds(self):
        cases = {
            "": "empty draft",
            "x" * 901: "longer than",
            "Here's the draft: hi": "matches",
            "I've passed it to PJ.": "claims an action",
            "See https://agent-net.artifacts/l2": "link not in the message",
            "Cheers.\n— PJ": "matches",
        }
        for body, why in cases.items():
            reasons = guard(body, "a message")
            self.assertTrue(any(why in r for r in reasons), (body, reasons))

    def test_facts_about_rush_are_not_claimed_actions(self):
        self.assertEqual(guard("I run on llama3.1:8b through Ollama.", "Which model?"), [])
        self.assertTrue(guard("I've run the benchmark.", "Benchmark it?"))
        self.assertTrue(guard("I just ran it.", "Run it?"))

    def test_links_from_the_message_are_fine(self):
        self.assertEqual(guard("Reading https://x.dev/a now.", "see https://x.dev/a"), [])


@unittest.skipUnless(importlib.util.find_spec("yaml"), "needs the analytics dependency group")
class GuardParityTest(unittest.TestCase):
    def test_guard_uses_the_checks_the_weapon_was_earned_against(self):
        import yaml

        from light_labs.agents.rush import autosend

        stage = yaml.safe_load(Path("evals/stages/reply-draft.yaml").read_text())
        self.assertEqual(autosend.MUST_NOT_MATCH, stage["defaults"]["must_not_match"])
        self.assertEqual(autosend.MAX_CHARS, stage["defaults"]["max_chars"])


class PolicyTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name))

    def sent(self, target, auto, kind="reply", resolved="2026-10-13T01:00:00+00:00"):
        i = self.store.enqueue(kind, target, "x", "c")
        path = self.store.root / "queue" / "pending" / f"{i['id']}.json"
        i.update(resolved=resolved, auto=auto)
        (self.store.root / "queue" / "sent" / path.name).write_text(json.dumps(i))
        path.unlink()

    def decide(self, settings=ON, kind="reply", target=DM, escalate=None):
        policy = Policy(settings, self.store, today="2026-10-13")
        return policy.decide(kind, target, "Thanks!", "Welcome!", escalate)

    def test_sends_a_clean_reply(self):
        self.assertEqual(self.decide(), (True, []))

    def test_off_escalated_or_kind_not_enabled(self):
        self.assertFalse(self.decide(settings={**ON, "enabled": False})[0])
        self.assertEqual(self.decide(escalate="do work"), (False, ["escalated"]))
        self.assertFalse(self.decide(settings={**ON, "kinds": ["comment"]})[0])
        with mock.patch.dict("os.environ", {"RUSH_AUTO_SEND": "0"}):
            self.assertEqual(self.decide(), (False, ["auto-send off"]))

    def test_one_auto_reply_per_thread_until_a_person_steps_in(self):
        self.sent(DM, auto=True)
        send, why = self.decide()
        self.assertFalse(send)
        self.assertIn("a person goes next", why[0])
        self.sent(DM, auto=False, resolved="2026-10-13T02:00:00+00:00")  # PJ approved one
        self.assertTrue(self.decide()[0])
        self.assertTrue(self.decide(target={"to": ["quill"]})[0])  # other threads unaffected

    def test_daily_cap(self):
        self.sent({"to": ["a"]}, auto=True)
        self.sent({"to": ["b"]}, auto=True)
        send, why = self.decide(target={"to": ["c"]})
        self.assertFalse(send)
        self.assertIn("daily cap of 2 reached", why)

    def test_flag_turns_the_kind_off(self):
        state = self.store.load()
        state["auto_send_off"] = ["reply"]
        self.store.save(state)
        self.assertFalse(self.decide()[0])
        self.assertTrue(self.decide(kind="comment", target={"task_id": "t1"})[0])


class HeartbeatAutoSendTest(unittest.TestCase):
    def run_tick(self, reply):
        with tempfile.TemporaryDirectory() as tmp:
            store, client = Store(Path(tmp)), PostingClient()
            client.items = [item("a1", "nova")]
            client.messages["a1"] = {"content": "Welcome to the board!", "summary": "hi"}
            hb = Heartbeat(
                client,
                FakeBrain(reply),
                store,
                "persona",
                actor="pj_agent",
                watch_tasks=[],
                name="Rush",
                signoff="— Rush",
                autosend=Policy(ON, store),
            )
            hb.tick(backfill=True)
            sent = [json.loads(p.read_text()) for p in (store.root / "queue/sent").glob("*")]
            pending = store.pending()
        return client.posted, sent, pending

    def test_clean_reply_is_posted_and_recorded_as_auto(self):
        posted, sent, pending = self.run_tick("Thanks, glad to be here!")
        self.assertEqual(len(posted), 1)
        self.assertTrue(sent[0]["auto"])
        self.assertEqual(sent[0]["drafted"], sent[0]["draft"])
        self.assertEqual(pending, [])

    def test_guarded_reply_waits_with_its_reasons(self):
        posted, sent, pending = self.run_tick("I've posted the numbers already.")
        self.assertEqual((posted, sent), ([], []))
        self.assertTrue(any("claims an action" in r for r in pending[0]["held"]))


if __name__ == "__main__":
    unittest.main()
