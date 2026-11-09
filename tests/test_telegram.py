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
        self.calls, self.updates, self.next_id, self.files = [], [], 100, {}

    def __call__(self, req, timeout=None):
        if "/file/bot" in req.full_url:  # a download: raw bytes, not a JSON envelope
            path = req.full_url.split("/file/botTOKEN/", 1)[1]
            self.calls.append(("download", {"path": path}))
            return io.BytesIO(self.files[path])
        method = req.full_url.rsplit("/", 1)[1]
        params = json.loads(req.data)
        self.calls.append((method, params))
        if method == "getUpdates":
            result, self.updates = self.updates, []
        elif method == "getFile":
            result = {"file_path": f"documents/{params['file_id']}.csv"}
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


STRONG = (
    b"Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,"
    b"Notes,Workout Notes,RPE\n"
    b'2026-11-07 06:00:00,"Push",40m,"Bench Press (Barbell)",1,135.0,8.0,0,0.0,"","",\n'
    b'2026-11-07 06:00:00,"Push",40m,"Bench Press (Barbell)",Rest Timer,0,0.0,0,120.0,,,\n'
    b'2026-11-08 06:00:00,"Push",40m,"Bench Press (Barbell)",2,135.0,8.0,0,0.0,,,\n'
)


class DropTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.wire = Wire()
        self.drops = self.root / "inbox"
        self.tg = Telegram(
            "TOKEN", PJ_CHAT, self.root / "telegram.json", opener=self.wire, drops=self.drops
        )

    def tearDown(self):
        self.tmp.cleanup()

    def doc(self, name="strong.csv", data=STRONG, chat=PJ_CHAT, size=None):
        self.wire.files["documents/f1.csv"] = data
        return {
            "message": {
                "chat": {"id": chat},
                "date": 1762600000,
                "document": {"file_id": "f1", "file_name": name, "file_size": size or len(data)},
            }
        }

    def test_csv_from_pj_lands_in_drops(self):
        self.tg.handle(self.doc(), None)
        (out,) = self.drops.glob("strong-*.csv")
        self.assertEqual(out.read_bytes(), STRONG)
        self.assertEqual(list(self.drops.glob("*.part")), [])
        self.assertEqual(
            self.wire.sent()[-1]["text"],
            f"Got 2 sets, 2026-11-07 to 2026-11-08. Saved {out.name}.",
        )

    def test_csv_that_isnt_strong_is_refused(self):
        self.tg.handle(self.doc(data=b"a,b\n1,2\n"), None)
        self.assertFalse(self.drops.exists())
        self.assertIn("Not a Strong export: header differs", self.wire.sent()[-1]["text"])

    def test_same_day_drop_replaces(self):
        self.tg.handle(self.doc(), None)
        more = STRONG + b'2026-11-08 07:00:00,"Pull",30m,"Pull Up",1,0,5.0,0,0.0,,,\n'
        self.tg.handle(self.doc(data=more), None)
        (out,) = self.drops.glob("strong-*.csv")
        self.assertIn(b"Pull Up", out.read_bytes())

    def test_not_a_csv_is_refused_without_download(self):
        self.tg.handle(self.doc(name="photo.jpg"), None)
        self.assertFalse(self.drops.exists())
        self.assertNotIn("getFile", [m for m, _ in self.wire.calls])
        self.assertIn("Not a CSV", self.wire.sent()[-1]["text"])

    def test_too_big_is_refused(self):
        self.tg.handle(self.doc(size=21 * 1024 * 1024), None)
        self.assertFalse(self.drops.exists())
        self.assertIn("20 MB", self.wire.sent()[-1]["text"])

    def test_other_chats_are_ignored(self):
        self.assertIsNone(self.tg.handle(self.doc(chat=7), None))
        self.assertEqual(self.wire.calls, [])

    def test_no_drops_dir_says_so(self):
        self.tg.drops = None
        self.tg.handle(self.doc(), None)
        self.assertIn("can't take files", self.wire.sent()[-1]["text"])
