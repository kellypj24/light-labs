"""Radar's tailnet page and the marker Rush reads. Synthetic names only."""

import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from light_labs.radar import digest, notice, page

PJ = "pj@example.com"
HOST = "mac.example.ts.net"
DIGEST = "\n".join(
    [
        "# Relationship Radar: week of 2026-11-06",
        "",
        "Counts and dates only; no message content.",
        "",
        "## Reach out this week",
        "",
        f"1. **{digest.safe('Carol <b>[x](http://evil.example)')}** (close): quiet 70 days.",
        "   Last contact: 70 days ago via imessage.",
        '   Opener: "Hey Carol, been too long."',
        "2. **Bob Example** (friends): 1.3x past your 30-day cadence.",
        "",
        "## Birthdays, next 14 days",
        "",
        "- Sat Nov 7: Alice Example, turns 40",
        "",
        "## Professional network",
        "",
        "No one to suggest yet (needs org data or a `network` circle).",
        "",
        "## Stats",
        "",
        "| Circle | Nov (to date) | Oct |",
        "|---|---:|---:|",
        "| inner | 4 | 9 |",
        "",
    ]
)


class TestRender(unittest.TestCase):
    def test_a_name_is_text_never_markup_or_a_link(self):
        out = page.render(DIGEST)
        self.assertIn("<strong>Carol &lt;b&gt;[x](http://evil.example)</strong>", out)
        self.assertNotIn("<b>", out)
        self.assertNotIn("<a", out)
        self.assertNotIn("\\", out)  # safe()'s escapes are read, not shown

    def test_structure(self):
        out = page.render(DIGEST)
        self.assertIn("<h1>Relationship Radar: week of 2026-11-06</h1>", out)
        self.assertEqual(out.count("<ol>"), 1)
        self.assertEqual(out.count("<li>"), 3)
        self.assertIn('<div class="sub">Last contact: 70 days ago via imessage.</div>', out)
        self.assertIn("<code>network</code>", out)
        self.assertIn("<th class=n>Oct</th>", out)
        self.assertIn("<td>inner</td><td class=n>4</td><td class=n>9</td>", out)
        self.assertNotIn("---", out)

    def test_an_unclosed_mark_is_closed(self):
        self.assertEqual(page.inline("**a `b"), "<strong>a <code>b</code></strong>")
        self.assertEqual(page.inline(r"1 \* 2 \| 3"), "1 * 2 | 3")


class TestServer(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "weekly-digest.md"
        self.page = page.Page(self.file, allowed=[PJ], hosts=[HOST])
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), page.handler(self.page))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        patch = mock.patch("builtins.print")  # the request log
        patch.start()
        self.addCleanup(patch.stop)

    def get(self, path="/", host=HOST, login=PJ, method="GET"):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}{path}", method=method
        )
        req.add_header("Host", host)
        if login:
            req.add_header("Tailscale-User-Login", login)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), e.headers

    def test_serves_the_digest_to_the_allowed_login_only(self):
        self.file.write_text(DIGEST)
        code, body, headers = self.get()
        self.assertEqual(code, 200)
        self.assertIn("Bob Example", body)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        for refused in (
            {"login": None},
            {"login": "someone@example.com"},
            {"host": "evil.example"},  # a rebound name, sending the login header itself
        ):
            code, body, _ = self.get(**refused)
            self.assertEqual(code, 403, refused)
            self.assertNotIn("Bob", body)

    def test_one_route_and_no_writes(self):
        self.file.write_text(DIGEST)
        for path in ("/digests/2026-11-06.md", "/../radar.duckdb", "/w/2026-W45"):
            self.assertEqual(self.get(path)[0], 404, path)
        self.assertEqual(self.get("/?x=1")[0], 200)
        for method in ("POST", "PUT", "DELETE"):
            self.assertEqual(self.get(method=method)[0], 501, method)

    def test_no_digest_yet(self):
        code, body, _ = self.get()
        self.assertEqual(code, 200)
        self.assertIn("No digest yet", body)

    def test_serve_binds_loopback(self):
        made = {}

        class Fake:
            def __init__(self, address, handler):
                made["address"] = address

            def serve_forever(self):
                pass

        with (
            mock.patch.object(page, "ThreadingHTTPServer", Fake),
            mock.patch.object(page, "tailnet_login", return_value=PJ),
            mock.patch.object(page, "tailnet_hosts", return_value={HOST}),
        ):
            page.serve(self.file)
        self.assertEqual(made["address"], ("127.0.0.1", page.PORT))


class TestNotice(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.var = Path(tmp.name)
        self.sent = []
        env = mock.patch.dict("os.environ", {"RADAR_URL": "http://mac.example.ts.net:8081/"})
        env.start()
        self.addCleanup(env.stop)

    def send(self, to, text):
        self.sent.append(text)

    def test_one_text_per_digest_and_nothing_but_the_link(self):
        self.assertEqual(notice.tick(self.send, self.var), [])  # no marker yet
        notice.mark(date(2026, 11, 6), self.var)
        self.assertEqual(notice.tick(self.send, self.var), ["texted the page link for 2026-11-06"])
        self.assertEqual(self.sent, ["Weekly picks are ready.\n\nhttp://mac.example.ts.net:8081"])
        self.assertEqual(notice.tick(self.send, self.var), [])
        notice.mark(date(2026, 11, 13), self.var)
        notice.tick(self.send, self.var)
        self.assertEqual(len(self.sent), 2)

    def test_without_a_url_the_date_waits(self):
        notice.mark(date(2026, 11, 6), self.var)
        with mock.patch.dict("os.environ", {"RADAR_URL": ""}):
            self.assertEqual(notice.tick(self.send, self.var), [])
        self.assertEqual(len(notice.tick(self.send, self.var)), 1)

    def test_a_marker_that_is_not_a_date_is_ignored(self):
        for junk in ('{"date": "Call +14155550199 now"}', '{"date": 7}', "[]", "not json"):
            notice.ready_path(self.var).parent.mkdir(parents=True, exist_ok=True)
            notice.ready_path(self.var).write_text(junk)
            self.assertEqual(notice.tick(self.send, self.var), [], junk)
        self.assertEqual(self.sent, [])

    def test_a_failed_send_is_retried(self):
        notice.mark(date(2026, 11, 6), self.var)

        def down(to, text):
            raise OSError("telegram unreachable")

        with self.assertRaises(OSError):
            notice.tick(down, self.var)
        self.assertEqual(len(notice.tick(self.send, self.var)), 1)


if __name__ == "__main__":
    unittest.main()
