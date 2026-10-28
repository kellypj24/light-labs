import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from light_labs.agents.rush import board
from light_labs.agents.rush.autosend import Policy
from light_labs.agents.rush.heartbeat import Heartbeat
from light_labs.core.store import Store
from tests.test_autosend import ON, PostingClient
from tests.test_rush import FakeBrain, item

TASK = {
    "id": "t1",
    "title": "Ask Rush about the harness",
    "status": "open",
    "updatedAt": "2026-10-28T10:00:00Z",
    "createdAt": "2026-10-27T10:00:00Z",
    "createdBy": "nova",
    "description": "Rush, which model?",
    "comments": [{"at": "2026-10-28T10:00:00Z", "author": "nova", "text": "Any news?"}],
}
OTHER = {**TASK, "id": "t2", "title": "Unrelated", "description": "x", "comments": []}


class CacheTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name))
        self.client = PostingClient()
        self.client.items = [item("a1", "nova")]
        self.client.messages["a1"] = {"id": "a1", "content": "Welcome!", "summary": "hi"}
        self.client.board = [TASK, OTHER]

    def test_tick_writes_the_cache(self):
        hb = Heartbeat(
            self.client, FakeBrain("Thanks!"), self.store, "persona", actor="pj_agent",
            watch_tasks=[], name="Rush", signoff="— Rush", mention=board.re.compile("Rush"),
        )  # fmt: skip
        hb.tick(backfill=True)
        snap = board.load(self.store.root)
        self.assertEqual([i["id"] for i in snap["inbox"]], [self.client.items[0]["id"]])
        self.assertEqual(snap["messages"]["a1"]["content"], "Welcome!")
        self.assertEqual([t["id"] for t in snap["tasks"]], ["t1", "t2"])

    def test_bodies_are_kept_while_in_the_inbox(self):
        board.save(self.store.root, self.client.items, [], {"a1": {"content": "Welcome!"}})
        snap = board.save(self.store.root, self.client.items)  # a tick with nothing new
        self.assertIn("a1", snap["messages"])
        self.assertEqual(board.save(self.store.root, [])["messages"], {})

    def test_live_fetch_leaves_rush_seen_state_alone(self):
        before = self.store.load()
        snap = board.fetch(self.client, "pj_agent", self.store.root)
        self.assertEqual(snap["messages"]["a1"]["content"], "Welcome!")
        self.assertEqual(self.store.load(), before)

    def test_overview_and_show(self):
        snap = board.save(self.store.root, self.client.items, [TASK, OTHER])
        later = datetime.fromisoformat(snap["at"]).astimezone(UTC).replace(year=2099)
        text = board.overview(snap, "pj_agent", at=later)
        self.assertIn("stale, use --live", text)
        self.assertIn("a1", text)
        self.assertIn("t1", text)
        self.assertNotIn("Unrelated", text)
        self.assertIn("nova: Any news?", text)
        self.assertIn("Any news?", board.show(*board.find(snap, "t1")))
        self.assertIn("(body not cached)", board.show(*board.find(snap, "a1")))
        self.assertIsNone(board.find(snap, "nope"))


class PostTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name))
        self.client = PostingClient()

    def post(self, text, target=None, settings=ON, dry_run=False):
        return board.post(
            self.client, self.store, Policy(settings, self.store), "pj_agent", "— Auto",
            "comment", target or {"task_id": "t1"}, text, dry_run=dry_run,
        )  # fmt: skip

    def sent(self):
        return [json.loads(p.read_text()) for p in (self.store.root / "queue/sent").glob("*")]

    def test_claims_and_links_are_allowed_for_auto(self):
        item_, held = self.post("I merged #70: https://github.com/x/y/pull/70")
        self.assertEqual(held, [])
        self.assertEqual(self.client.posted[0][2], f"{item_['draft']}")
        self.assertTrue(item_["draft"].endswith("— Auto"))
        [rec] = self.sent()
        self.assertEqual((rec["author"], rec["auto"]), ("auto", True))

    def test_other_guards_still_hold_and_queue_for_pj(self):
        item_, held = self.post("x" * 901)
        self.assertEqual(self.client.posted, [])
        self.assertIn("longer than", held[0])
        self.assertEqual(self.store.pending()[0]["id"], item_["id"])
        _, held = self.post("hi", settings={**ON, "enabled": False})
        self.assertEqual(held, ["auto-send off"])

    def test_no_per_thread_limit_and_own_daily_cap(self):
        self.post("one")
        self.post("two")  # per_thread is 1 for Rush, not for Auto
        self.assertEqual(len(self.client.posted), 2)
        _, held = self.post("three")  # ON caps at 2
        self.assertIn("daily cap of 2 reached", held)

    def test_auto_posts_do_not_use_rush_cap(self):
        self.post("one")
        self.post("two")
        policy = Policy(ON, self.store)
        self.assertTrue(policy.decide("reply", {"to": ["nova"]}, "Thanks!", "Hi", None)[0])

    def test_post_supersedes_rush_pending_draft_in_the_thread(self):
        old = self.store.enqueue("comment", {"task_id": "t1"}, "Rush's draft", "c")
        self.post("Answered.")
        self.assertEqual(self.store.pending(), [])
        rejected = json.loads((self.store.root / f"queue/rejected/{old['id']}.json").read_text())
        self.assertTrue(rejected["reason"].startswith("superseded by "))

    def test_dry_run_posts_nothing(self):
        self.assertEqual(self.post("hi", dry_run=True), (None, []))
        self.assertEqual((self.client.posted, self.store.pending(), self.sent()), ([], [], []))


if __name__ == "__main__":
    unittest.main()
