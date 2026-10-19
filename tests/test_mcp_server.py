import io
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
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
        self.assertEqual(names, set(mcp_server.HANDLERS))

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

    def test_board_keeps_recent_open_tasks_and_flags_mentions(self):
        now = datetime.now(UTC)
        ago = lambda h: (now - timedelta(hours=h)).isoformat()
        tasks = [
            {"id": "a", "title": "ping PJ", "status": "doing", "updatedAt": ago(1),
             "comments": [{"author": "nova", "at": ago(1), "text": "x" * 500}]},
            {"id": "b", "title": "quiet", "status": "backlog", "updatedAt": ago(2)},
            {"id": "c", "title": "finished", "status": "done", "updatedAt": ago(1)},
            {"id": "d", "title": "stale", "status": "doing", "updatedAt": ago(48)},
        ]  # fmt: skip
        client = mock.Mock(list_tasks=mock.Mock(return_value=tasks))
        got = mcp_server.board_tasks(client=client)
        self.assertEqual([t["id"] for t in got], ["a", "b"])
        self.assertTrue(got[0]["mentions_pj_or_rush"])
        self.assertEqual(len(got[0]["last_comment"]["text"]), mcp_server.EXCERPT)
        only = mcp_server.board_tasks(mentions_only=True, client=client)
        self.assertEqual([t["id"] for t in only], ["a"])
        self.assertEqual(
            [t["id"] for t in mcp_server.board_tasks(status="done", client=client)], ["c"]
        )

    def test_github_status_reads_prs_and_failing_ci(self):
        (self.var / "rush").mkdir()
        (self.var / "rush" / "github.json").write_text(json.dumps({"repos": {
            "me/a": {"ci": {"CI": {"failing": True}, "Lint": {"failing": False}}},
            "me/b": {"ci": {"CI": {"failing": False}}},
        }}))  # fmt: skip
        answers = {
            "search": [{"repository": {"nameWithOwner": "me/a"}, "number": 7, "title": "t"}],
            "pr": {"isDraft": False, "reviewDecision": "",
                   "statusCheckRollup": [{"conclusion": "FAILURE"}, {"status": "IN_PROGRESS"}]},
        }  # fmt: skip

        def run(args, **kw):
            return mock.Mock(stdout=json.dumps(answers[args[1]]))

        got = mcp_server.github_status(run=run)
        pr = got["open_prs"][0]
        self.assertEqual((pr["repo"], pr["review"], pr["checks_failing"], pr["checks_pending"]),
                         ("me/a", None, 1, 1))  # fmt: skip
        self.assertEqual(got["ci_failing"], {"me/a": ["CI"]})

    def test_robot_status(self):
        roll = self.var / "roll"
        roll.mkdir()
        (roll / "journal.md").write_text("- one\n- two\n- three\n")
        (roll / "report.json").write_text(json.dumps(
            {"inbox": 5, "unread": 1, "rules": [{"id": "r", "count": 2}]}))  # fmt: skip
        got = mcp_server.robot_status("roll", lines=2)
        self.assertEqual(got["journal"], ["- two", "- three"])
        self.assertEqual(got["last_report"]["rules"], {"r": 2})
        self.assertIn("taken", got["last_report"])
        self.assertTrue(self.tool("robot_status", robot="bass")[0])

    def test_rush_present_shows_drafts_with_buttons_and_sends_nothing(self):
        store = Store(self.var / "rush")
        a = store.enqueue("comment", {"task_id": "t1"}, "looks good", "nova: done?")
        b = store.enqueue("comment", {"task_id": "t2"}, "on it", "quill: ready?")
        tg = mock.Mock()
        got = mcp_server.rush_present([a["id"], "gone", a["id"]], telegram=tg)
        self.assertEqual(got["shown_in_rush_chat"], [a["id"]])
        self.assertEqual(got["not_pending"], ["gone"])
        tg.draft.assert_called_once()
        self.assertEqual(tg.draft.call_args.args[0]["id"], a["id"])
        self.assertIn("looks good", tg.draft.call_args.args[1])
        self.assertEqual({i["id"] for i in store.pending()}, {a["id"], b["id"]})  # still pending
        with self.assertRaises(ValueError):
            mcp_server.rush_present([str(n) for n in range(11)], telegram=tg)

    def test_unknown_method_and_tool(self):
        replies = self.call(
            {"jsonrpc": "2.0", "id": 1, "method": "resources/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "send"}},
        )
        self.assertEqual([r["error"]["code"] for r in replies], [-32601, -32602])


if __name__ == "__main__":
    unittest.main()
