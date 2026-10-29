import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from light_labs.agents.rush.remote import Remote, board_view, handler
from light_labs.core.store import Store

PJ = "pj@example.com"


class EdgeStub:
    def __init__(self):
        self.posted = []
        self.board = [
            {"id": "t1", "title": "For Rush: a trial", "updatedAt": "2026-01-02", "comments": []},
            {
                "id": "t2",
                "title": "Unrelated",
                "updatedAt": "2026-01-03",
                "comments": [{"author": "a", "text": "nothing here"}],
            },
            {
                "id": "t3",
                "title": "Other",
                "updatedAt": "2026-01-04",
                "comments": [{"author": "a", "text": "PJ, thoughts?"}],
            },
        ]

    def comment(self, actor, task_id, text):
        self.posted.append(("comment", task_id, text))
        return {"id": "obj1"}

    def send(self, actor, to, content, summary=None, in_reply_to=None):
        self.posted.append(("reply", to, content))
        return {"id": "obj2"}

    def list_tasks(self):
        return self.board

    def task(self, task_id):
        return next(t for t in self.board if t["id"] == task_id)

    def inbox(self, actor):
        return {"items": []}


class RemoteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.edge = EdgeStub()
        self.ticks = []
        rush = SimpleNamespace(ACTOR="pj_agent", MAIL_ACCOUNTS=["me@x"])
        self.remote = Remote(
            self.store, rush, client=self.edge, allowed=[PJ], tick=lambda: self.ticks.append(1)
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.remote))
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, path, form=None, login=PJ):
        data = None if form is None else urllib.parse.urlencode(form).encode()
        req = urllib.request.Request(self.base + path, data=data)
        if login:
            req.add_header("Tailscale-User-Login", login)
        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_refuses_without_an_allowed_login(self):
        self.assertEqual(self.call("/", login=None)[0], 403)
        self.assertEqual(self.call("/", login="someone@else.com")[0], 403)
        self.assertEqual(self.call("/")[0], 200)

    def test_post_needs_the_page_token(self):
        item = self.store.enqueue("comment", {"task_id": "t1"}, "hi", "ctx")
        code, _ = self.call(f"/approve/{item['id']}", {"text": "hi", "token": "wrong"})
        self.assertEqual(code, 403)
        self.assertEqual(self.edge.posted, [])

    def test_send_posts_the_edited_draft_and_keeps_the_original(self):
        item = self.store.enqueue("comment", {"task_id": "t1"}, "robot draft", "ctx")
        self.assertIn("robot draft", self.call("/")[1])
        code, _ = self.call(
            f"/approve/{item['id']}", {"text": "PJ's version", "token": self.remote.token}
        )
        self.assertEqual(code, 303)
        self.assertEqual(self.edge.posted, [("comment", "t1", "PJ's version")])
        sent = json.loads((self.store.root / "queue/sent" / f"{item['id']}.json").read_text())
        self.assertEqual((sent["draft"], sent["drafted"]), ("PJ's version", "robot draft"))
        self.assertEqual(self.call(f"/approve/{item['id']}", {"token": self.remote.token})[0], 404)

    def test_reject_records_the_reason(self):
        item = self.store.enqueue("reply", {"to": ["muse"]}, "d", "ctx")
        self.call(f"/reject/{item['id']}", {"reason": "off topic", "token": self.remote.token})
        rejected = json.loads(
            (self.store.root / "queue/rejected" / f"{item['id']}.json").read_text()
        )
        self.assertEqual(rejected["reason"], "off topic")
        self.assertEqual(self.store.pending(), [])

    def test_comment_is_signed_as_pj(self):
        self.call("/comment/t1", {"text": "On it.", "token": self.remote.token})
        self.assertEqual(self.edge.posted, [("comment", "t1", "On it.\n\n— PJ (via pj_agent)")])

    def test_tick_runs_in_the_background(self):
        self.assertEqual(self.call("/tick", {"token": self.remote.token})[0], 303)
        self.remote.ticking.acquire()  # waits for the tick thread to finish
        self.remote.ticking.release()
        self.assertEqual(self.ticks, [1])

    def test_mail_page_lists_triaged_mail_with_gmail_links(self):
        (self.store.root / "mail").mkdir(exist_ok=True)
        item = {"id": "m1", "thread": "t1", "account": "me@x", "from": "Dana <d@x>",
                "subject": "Thursday?", "label": "needs_reply", "summary": "asks about 3pm",
                "by": "model", "date": "Mon"}  # fmt: skip
        (self.store.root / "mail" / "me@x.jsonl").write_text(json.dumps(item) + "\n")
        body = self.call("/mail")[1]
        self.assertIn("needs reply (1)", body)
        self.assertIn("asks about 3pm", body)
        self.assertIn("authuser=me@x#all/t1", body)

    def test_usage_page_reports_when_the_marts_are_missing(self):
        import duckdb

        self.remote.usage_db = Path(self.tmp.name) / "lab.duckdb"
        duckdb.connect(str(self.remote.usage_db)).close()
        code, body = self.call("/usage")
        self.assertEqual(code, 200)
        self.assertIn("Claude Code usage", body)
        self.assertIn("just analytics", body)

    def test_lab_needs_login_and_sends_csp(self):
        snap = {
            "at": "2026-10-28T21:00:00+00:00",
            "job": None,
            "machine": {
                "thermal": "nominal",
                "battery_c": None,
                "speed_limit": 100,
                "load_1": 1.0,
                "cores": 10,
                "pressure": "normal",
                "swap_mb": 10.0,
            },
            "limits": {"swap_growth_mb": 2048, "battery_c": 40.0},
            "hot": "",
            "critical": "",
            "start_ok": True,
            "why_not": "",
            "busy": [],
            "dagster": [],
            "history": [],
        }
        with mock.patch("light_labs.core.monitor.snapshot", return_value=snap):
            for path in ("/lab", "/lab.json", "/lab.js"):
                self.assertEqual(self.call(path, login=None)[0], 403, path)
            code, body = self.call("/lab")
            self.assertEqual(code, 200)
            self.assertIn('<script src="/lab.js">', body)
            self.assertIn("No heavy job running", body)
            self.assertIn("No heavy job running", json.loads(self.call("/lab.json")[1])["html"])
        req = urllib.request.Request(self.base + "/lab.js")
        req.add_header("Tailscale-User-Login", PJ)
        with urllib.request.urlopen(req) as r:
            csp = r.headers["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))
        self.assertNotIn("unsafe-inline", script_src)
        self.assertIn("frame-ancestors 'none'", csp)

    def test_board_shows_tasks_naming_pj_or_rush_newest_first(self):
        self.assertEqual([t["id"] for t in board_view(self.edge.board, "pj_agent")], ["t3", "t1"])
        self.assertIn("For Rush: a trial", self.call("/board")[1])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


if __name__ == "__main__":
    unittest.main()
