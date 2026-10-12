import tempfile
import unittest
from pathlib import Path

from light_labs.agents.rush.heartbeat import Heartbeat, clean, split_escalation
from light_labs.core.store import Store

HUB = "http://127.0.0.1:8710"


def item(mid, sender, broadcast=False):
    return {
        "id": f"{HUB}/objects/{mid}",
        "attributedTo": f"{HUB}/actors/{sender}",
        "summary": "s",
        "broadcast": broadcast,
    }


class FakeClient:
    def __init__(self):
        self.items, self.messages, self.tasks = [], {}, {}

    def inbox(self, actor):
        return {"items": self.items}

    def message(self, mid):
        return self.messages[mid]

    def task(self, task_id):
        return self.tasks[task_id]


class FakeBrain:
    def __init__(self, reply="hello there"):
        self.reply, self.prompts = reply, []

    def think(self, system, user):
        self.prompts.append(user)
        return self.reply


class HeartbeatTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.client, self.brain = FakeClient(), FakeBrain()
        self.client.tasks["t1"] = {"title": "Lenses", "comments": []}
        self.hb = Heartbeat(
            self.client,
            self.brain,
            self.store,
            "persona",
            actor="pj_agent",
            watch_tasks=["t1"],
            name="Rush",
            signoff="— Rush (DLN-100, pj_agent)",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_tick_seeds_backlog_without_drafting(self):
        self.client.items = [item("a1", "alpha")]
        self.client.tasks["t1"]["comments"] = [{"author": "alpha", "text": "old"}]
        self.assertEqual(self.hb.tick(), [])
        self.assertEqual(self.store.pending(), [])
        state = self.store.load()
        self.assertEqual(state["seen_messages"], ["a1"])
        self.assertEqual(state["seen_comments"], {"t1": 1})

    def test_backfill_drafts_backlog(self):
        self.client.items = [item("a1", "alpha")]
        self.client.messages["a1"] = {"content": "hi rush", "summary": "hello"}
        drafted = self.hb.tick(backfill=True)
        self.assertEqual(len(drafted), 1)
        self.assertEqual(drafted[0]["target"]["to"], ["alpha"])
        self.assertIn("hi rush", self.brain.prompts[0])
        self.assertTrue(drafted[0]["draft"].endswith("— Rush (DLN-100, pj_agent)"))

    def test_new_messages_after_seed(self):
        self.hb.tick()
        self.client.items = [
            item("b2", "bravo"),
            item("c3", "pj_agent"),
            item("d4", "operator", broadcast=True),
        ]
        self.client.messages["b2"] = {"content": "question", "summary": None}
        drafted = self.hb.tick()
        self.assertEqual([d["target"]["to"] for d in drafted], [["bravo"]])
        self.assertEqual(len(self.hb.tick()), 0)  # nothing drafted twice

    def test_new_task_comments_skip_own(self):
        self.hb.tick()
        self.client.tasks["t1"]["comments"] = [
            {"author": "charlie", "text": "review"},
            {"author": "pj_agent", "text": "mine"},
        ]
        drafted = self.hb.tick()
        self.assertEqual(len(drafted), 1)
        self.assertEqual(drafted[0]["target"], {"task_id": "t1"})

    def test_callable_persona_gets_the_message(self):
        seen = []

        def persona(text):
            seen.append(text)
            return "system for this message"

        self.hb.persona = persona
        self.client.items = [item("a1", "alpha")]
        self.client.messages["a1"] = {"content": "please write a script"}
        self.hb.tick(backfill=True)
        self.assertIn("please write a script", seen[0])

    def test_comment_prompt_includes_thread(self):
        self.client.tasks["t1"]["comments"] = [{"author": "alpha", "text": "first idea"}]
        self.hb.tick()
        self.client.tasks["t1"]["comments"].append({"author": "charlie", "text": "a review"})
        self.hb.tick()
        self.assertIn("first idea", self.brain.prompts[-1])
        self.assertIn("a review", self.brain.prompts[-1])

    def test_escalation_writes_file(self):
        self.brain.reply = "ESCALATE: build lens v3\nOn it, will report back."
        self.client.items = [item("a1", "charlie")]
        self.client.messages["a1"] = {"content": "please build v3"}
        drafted = self.hb.tick(backfill=True)
        self.assertEqual(drafted[0]["escalate"], "build lens v3")
        self.assertTrue(drafted[0]["draft"].startswith("On it"))
        self.assertTrue((self.store.root / "escalations" / f"{drafted[0]['id']}.md").exists())

    def test_queue_resolve(self):
        i = self.store.enqueue("reply", {"to": ["alpha"]}, "d", "c")
        self.store.resolve(i["id"], "sent", result_id="x")
        self.assertEqual(self.store.pending(), [])
        self.assertTrue((self.store.root / "queue/sent" / f"{i['id']}.json").exists())


class HelpersTest(unittest.TestCase):
    def test_clean_strips_header_and_signoff(self):
        self.assertEqual(clean("DRAFT\n\nHi alpha.\n\nBest,\nRush\n"), "Hi alpha.")
        self.assertEqual(clean("Draft:\nHi.\n\nRush"), "Hi.")
        self.assertEqual(clean("Rush here, hi."), "Rush here, hi.")

    def test_clean_unwraps_quotes(self):
        self.assertEqual(clean('"Hi alpha."'), "Hi alpha.")

    def test_split_escalation_anywhere(self):
        esc, body = split_escalation("Sure thing.\n\nESCALATE: write the script\nHolding.")
        self.assertEqual(esc, "write the script")
        self.assertEqual(body, "Sure thing.\n\nHolding.")

    def test_split_escalation(self):
        self.assertEqual(split_escalation("hi"), (None, "hi"))
        self.assertEqual(split_escalation("escalate: x\nbody"), ("x", "body"))


if __name__ == "__main__":
    unittest.main()
