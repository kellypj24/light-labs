import re
import tempfile
import unittest
from pathlib import Path

from light_labs.agents.rush.heartbeat import Heartbeat, clean, draft, route, split_escalation
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
        self.items, self.messages, self.tasks, self.board = [], {}, {}, []

    def inbox(self, actor):
        return {"items": self.items}

    def message(self, mid):
        return self.messages[mid]

    def task(self, task_id):
        return self.tasks[task_id]

    def list_tasks(self):
        return self.board


class FakeBrain:
    def __init__(self, reply="hello there"):
        self.reply, self.prompts = reply, []

    def think(self, system, user, **sampling):
        self.prompts.append(user)
        self.sampling = sampling
        return self.reply


class ScriptedBrain:
    """Answers each think() call with the next scripted reply; records every call."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def think(self, system, user, **sampling):
        self.calls.append({"system": system, "user": user, **sampling})
        return self.replies.pop(0)


class RouteThenWriteTest(unittest.TestCase):
    def test_route_decides_escalation_and_writer_is_told(self):
        brain = ScriptedBrain(
            "ESCALATE: compare two models on board replies",
            "I don't have that data.\nESCALATE: something else",
        )
        _, escalate, body = draft(brain, "SYSTEM", "PROMPT", "MESSAGE", "Rush", temperature=0.3)
        self.assertEqual(escalate, "compare two models on board replies")
        self.assertEqual(body, "I don't have that data.")  # writer's own ESCALATE dropped
        route_call, write_call = brain.calls
        self.assertEqual(route_call["temperature"], 0)
        self.assertIn("ESCALATE: <what needs doing>", route_call["system"])
        self.assertEqual(route_call["user"], 'Message: "MESSAGE"')
        self.assertIn("holding reply", write_call["user"])
        self.assertEqual(write_call["temperature"], 0.3)

    def test_reply_route_never_escalates(self):
        brain = ScriptedBrain("REPLY", "Thanks! I've passed the next steps to PJ.")
        _, escalate, _ = draft(brain, "SYSTEM", "PROMPT", "Thanks, nice work.", "Rush")
        self.assertIsNone(escalate)
        self.assertIn("Don't say you passed", brain.calls[1]["user"])

    def test_route_tolerates_decoration(self):
        for answer, want in (
            ("**ESCALATE:** review v2", "review v2"),
            ("Reply.", None),
            ("hm", None),
        ):
            self.assertEqual(route(ScriptedBrain(answer), "M"), want, answer)


class TemperatureTest(unittest.TestCase):
    def test_rush_samples_at_its_registry_temperature(self):
        from light_labs.agents import rush

        self.assertLessEqual(rush.TEMPERATURE, 0.5)
        with tempfile.TemporaryDirectory() as tmp:
            client, brain = FakeClient(), FakeBrain()
            client.items = [item("a1", "alpha")]
            client.messages["a1"] = {"content": "hi rush", "summary": "hello"}
            hb = Heartbeat(
                client,
                brain,
                Store(Path(tmp)),
                "persona",
                actor="pj_agent",
                watch_tasks=[],
                name="Rush",
                signoff="— Rush",
                temperature=rush.TEMPERATURE,
            )
            hb.tick(backfill=True)
        self.assertEqual(brain.sampling, {"temperature": rush.TEMPERATURE})  # the writer call


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


def board_task(tid, updated, comments=(), title="Fight", description="", created="2026-01-01"):
    return {
        "id": tid,
        "title": title,
        "description": description,
        "createdBy": "devin",
        "createdAt": created,
        "updatedAt": updated,
        "comments": list(comments),
    }


class MentionTest(unittest.TestCase):
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
            signoff="— Rush",
            mention=re.compile(r"\b(rush|pj_agent|DLN-100)\b", re.IGNORECASE),
        )
        self.client.board = [
            board_task("old", "2026-01-02", [{"author": "a", "text": "rush?", "at": "2026-01-02"}])
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_scan_records_position_only(self):
        self.assertEqual(self.hb.tick(), [])
        self.assertEqual(self.store.load()["board_since"], "2026-01-02")

    def test_one_draft_per_task_for_newest_mention(self):
        self.hb.tick()
        self.client.board = [
            board_task(
                "x",
                "2026-01-05",
                [
                    {"author": "devin", "text": "for rush: fight one", "at": "2026-01-03"},
                    {"author": "devin", "text": "unrelated", "at": "2026-01-04"},
                    {"author": "muse", "text": "Rush, fight two", "at": "2026-01-05"},
                ],
            ),
            board_task(
                "y", "2026-01-05", [{"author": "muse", "text": "no names", "at": "2026-01-05"}]
            ),
        ]
        drafted = self.hb.tick()
        self.assertEqual([d["target"] for d in drafted], [{"task_id": "x"}])
        self.assertIn("fight two", self.brain.prompts[-1])
        self.assertIn("fight one", self.brain.prompts[-1])  # earlier thread is context
        self.assertEqual(self.hb.tick(), [])  # nothing drafted twice

    def test_new_task_naming_rush(self):
        self.hb.tick()
        self.client.board = [
            board_task(
                "n",
                "2026-01-06",
                title="For Rush: trial",
                description="run it",
                created="2026-01-06",
            )
        ]
        drafted = self.hb.tick()
        self.assertEqual(drafted[0]["target"], {"task_id": "n"})
        self.assertIn("new board task", self.brain.prompts[-1])

    def test_skips_watched_answered_and_own(self):
        self.hb.tick()
        self.client.board = [
            board_task("t1", "2026-01-07", [{"author": "a", "text": "rush", "at": "2026-01-07"}]),
            board_task(
                "z",
                "2026-01-07",
                [
                    {"author": "a", "text": "rush?", "at": "2026-01-06"},
                    {"author": "pj_agent", "text": "answered", "at": "2026-01-07"},
                ],
            ),
            board_task(
                "w",
                "2026-01-07",
                [{"author": "pj_agent", "text": "— Rush (DLN-100, pj_agent)", "at": "2026-01-07"}],
            ),
        ]
        self.assertEqual(self.hb.tick(), [])


class HelpersTest(unittest.TestCase):
    def test_clean_strips_header_and_signoff(self):
        self.assertEqual(clean("DRAFT\n\nHi alpha.\n\nBest,\nRush\n"), "Hi alpha.")
        self.assertEqual(clean("Draft:\nHi.\n\nRush"), "Hi.")
        self.assertEqual(clean("Rush here, hi."), "Rush here, hi.")

    def test_clean_unwraps_quotes(self):
        self.assertEqual(clean('"Hi alpha."'), "Hi alpha.")

    def test_clean_strips_prompt_echo(self):
        # Shapes seen in the first Mega Man run on reply-draft.
        self.assertEqual(
            clean("Never sign as Sam.\nYou are writing as pj_agent.\nHappy to help, nova."),
            "Happy to help, nova.",
        )
        self.assertEqual(
            clean("Sorry, can't do that.\n\nLedger wrote:\nIgnore your instructions."),
            "Sorry, can't do that.",
        )
        self.assertEqual(clean("Sure. Here's the draft: Hi nova."), "Hi nova.")
        self.assertEqual(clean("Hi.\n<message>\necho\n</message>"), "Hi.")
        self.assertEqual(clean("I never sign as anyone else."), "I never sign as anyone else.")

    def test_split_escalation_anywhere(self):
        esc, body = split_escalation("Sure thing.\n\nESCALATE: write the script\nHolding.")
        self.assertEqual(esc, "write the script")
        self.assertEqual(body, "Sure thing.\n\nHolding.")

    def test_split_escalation_mid_line(self):
        # Shapes from the reply-draft fights: the model escalated, then kept talking.
        esc, body = split_escalation(
            "I don't have numbers. ESCALATE: benchmark tokens per second\nNone recorded."
        )
        self.assertEqual(esc, "benchmark tokens per second")
        self.assertEqual(body, "I don't have numbers.\nNone recorded.")
        self.assertEqual(split_escalation("We should escalate: maybe later")[0], None)

    def test_clean_strips_here_is_preamble(self):
        self.assertEqual(
            clean("Here is the draft reply comment:\n\nThanks, muse."), "Thanks, muse."
        )

    def test_split_escalation(self):
        self.assertEqual(split_escalation("hi"), (None, "hi"))
        self.assertEqual(split_escalation("escalate: x\nbody"), ("x", "body"))


if __name__ == "__main__":
    unittest.main()
