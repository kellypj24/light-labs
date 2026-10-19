import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from light_labs.core import mcp_server
from light_labs.core.store import Store


class McpServerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.var = Path(tmp.name)
        patch = mock.patch.object(mcp_server.config, "VAR", self.var)
        patch.start()
        self.addCleanup(patch.stop)

    def call(self, *msgs):
        out = io.StringIO()
        mcp_server.serve(io.StringIO("".join(json.dumps(m) + "\n" for m in msgs)), out)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def tool(self, name, **arguments):
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": name, "arguments": arguments}}  # fmt: skip
        result = self.call(msg)[0]["result"]
        return result["isError"], result["content"][0]["text"]

    def test_handshake_and_tool_list(self):
        replies = self.call(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        self.assertEqual(len(replies), 2)  # the notification gets no answer
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "light-labs")
        names = {t["name"] for t in replies[1]["result"]["tools"]}
        self.assertEqual(names, {"queue_pending", "queue_item", "mail_recent"})

    def test_queue_lists_pending_across_robots(self):
        store = Store(self.var / "rush")
        a = store.enqueue("reply", {"to": ["nova"]}, "hi", "nova: hello")
        b = store.enqueue("comment", {"task_id": "t1"}, "done", "c")
        store.resolve(b["id"], "sent")
        is_error, text = self.tool("queue_pending")
        self.assertFalse(is_error)
        items = json.loads(text)
        self.assertEqual([(i["id"], i["robot"]) for i in items], [(a["id"], "rush")])
        self.assertEqual(
            json.loads(self.tool("queue_item", id=a["id"])[1])["context"], "nova: hello"
        )
        self.assertTrue(self.tool("queue_item", id="nope")[0])

    def test_mail_is_filtered_newest_first_and_has_no_body(self):
        mail = self.var / "rush" / "mail"
        mail.mkdir(parents=True)
        rows = [
            {"id": "1", "account": "a@x", "label": "fyi", "summary": "old", "snippet": "secret"},
            {"id": "2", "account": "a@x", "label": "needs_reply", "summary": "ask"},
            {"id": "3", "account": "a@x", "label": "fyi", "summary": "new"},
        ]
        (mail / "a@x.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (mail / "disagreements.jsonl").write_text(json.dumps(rows[0]) + "\n")
        got = json.loads(self.tool("mail_recent", label="fyi")[1])
        self.assertEqual([m["id"] for m in got], ["3", "1"])
        self.assertNotIn("snippet", got[0])

    def test_unknown_method_and_tool(self):
        replies = self.call(
            {"jsonrpc": "2.0", "id": 1, "method": "resources/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "send"}},
        )
        self.assertEqual([r["error"]["code"] for r in replies], [-32601, -32602])


if __name__ == "__main__":
    unittest.main()
