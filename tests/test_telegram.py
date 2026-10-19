import io
import json
import tempfile
import unittest
from pathlib import Path

from light_labs.agents.rush.telegram import Telegram
from light_labs.core.store import Store

PJ_CHAT = 42


class Wire:
    """Stands in for urlopen: records each Bot API call, answers with canned results."""

    def __init__(self):
        self.calls, self.updates, self.next_id = [], [], 100

    def __call__(self, req, timeout=None):
        method = req.full_url.rsplit("/", 1)[1]
        params = json.loads(req.data)
        self.calls.append((method, params))
        if method == "getUpdates":
            result, self.updates = self.updates, []
        elif method == "sendMessage":
            self.next_id += 1
            result = {"message_id": self.next_id}
        else:
            result = True
        return io.BytesIO(json.dumps({"ok": True, "result": result}).encode())

    def sent(self):
        return [p for m, p in self.calls if m == "sendMessage"]


class FakeRemote:
    def __init__(self, store):
        self.store, self.approved, self.rejected, self.ticks = store, [], [], 0

    def approve(self, item_id, text):
        self.store.get(item_id)  # FileNotFoundError when already handled
        self.approved.append((item_id, text))

    def reject(self, item_id, reason):
        self.rejected.append((item_id, reason))

    def start_tick(self):
        self.ticks += 1
        return True


class TelegramTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.wire = Wire()
        self.tg = Telegram("TOKEN", PJ_CHAT, self.store.root / "telegram.json", opener=self.wire)
        self.remote = FakeRemote(self.store)
        self.item = self.store.enqueue("comment", {"task_id": "t1"}, "Thanks!", "muse: hi")
        self.tg.draft(self.item, "Rush: muse on t1")  # message 101

    def tearDown(self):
        self.tmp.cleanup()

    def update(self, **body):
        self.wire.updates.append({"update_id": len(self.wire.calls), **body})
        self.tg.poll_once(self.remote, timeout=0)

    def message(self, text, chat=PJ_CHAT, reply_to=None):
        msg = {"chat": {"id": chat}, "text": text}
        if reply_to:
            msg["reply_to_message"] = {"message_id": reply_to}
        self.update(message=msg)

    def test_draft_has_send_and_reject_buttons(self):
        buttons = self.wire.sent()[0]["reply_markup"]["inline_keyboard"][0]
        self.assertEqual(
            [b["callback_data"] for b in buttons],
            [f"send:{self.item['id']}", f"reject:{self.item['id']}"],
        )
        self.assertEqual(self.wire.sent()[0]["chat_id"], str(PJ_CHAT))

    def test_send_button_approves_as_drafted(self):
        self.update(
            callback_query={
                "id": "q1",
                "data": f"send:{self.item['id']}",
                "message": {"message_id": 101, "chat": {"id": PJ_CHAT}, "text": "Rush: muse"},
            }
        )
        self.assertEqual(self.remote.approved, [(self.item["id"], None)])
        self.assertIn(
            ("answerCallbackQuery", {"callback_query_id": "q1", "text": "Sent"}), self.wire.calls
        )

    def test_reply_with_text_sends_pjs_version(self):
        self.message("Thanks, muse. More soon.", reply_to=101)
        self.assertEqual(self.remote.approved, [(self.item["id"], "Thanks, muse. More soon.")])

    def test_reply_no_rejects_with_reason(self):
        self.message("no: wrong thread", reply_to=101)
        self.assertEqual(self.remote.rejected, [(self.item["id"], "wrong thread")])

    def test_words_starting_with_no_are_not_rejections(self):
        self.message("Nothing to add, send it.", reply_to=101)
        self.assertEqual(self.remote.rejected, [])
        self.assertEqual(self.remote.approved, [(self.item["id"], "Nothing to add, send it.")])

    def test_ignores_other_chats(self):
        self.message("/tick", chat=7)
        self.update(
            callback_query={
                "id": "q2",
                "data": f"send:{self.item['id']}",
                "message": {"message_id": 101, "chat": {"id": 7}},
            }
        )
        self.assertEqual((self.remote.ticks, self.remote.approved), (0, []))

    def test_commands(self):
        self.message("/tick")
        self.assertEqual(self.remote.ticks, 1)
        self.message("/queue")
        self.assertIn("Rush: muse on t1", self.wire.sent()[-1]["text"])
        self.message("hello?")
        self.assertIn("/queue lists", self.wire.sent()[-1]["text"])

    def test_offset_advances_so_updates_are_handled_once(self):
        self.message("/tick")
        self.tg.poll_once(self.remote, timeout=0)
        self.assertEqual(self.remote.ticks, 1)
        offset = [p["offset"] for m, p in self.wire.calls if m == "getUpdates"][-1]
        self.assertGreater(offset, 0)


if __name__ == "__main__":
    unittest.main()
