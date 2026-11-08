"""Compile the Messages helper's test build; run it against a synthetic chat.db (macOS)."""

import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from light_labs.radar import doctor, helper
from light_labs.radar.helper import SOURCE
from light_labs.radar.sources.base import SyncContext, run_source
from light_labs.radar.sources.imessage import IMessageSource
from tests.radar_support import FIXTURES, RadarCase

ON_MAC = sys.platform == "darwin" and shutil.which("swiftc") is not None
_BUILDS: dict[str, Path] = {}


def build(name: str, flags: list[str]) -> Path:
    """One compile per flavour per test run (swiftc takes a couple of seconds)."""
    if name not in _BUILDS:
        out = Path(tempfile.mkdtemp()) / name
        subprocess.run(
            ["swiftc", "-O", "-D", "RADAR_TEST", *flags, "-o", str(out), str(SOURCE), "-lsqlite3"],
            check=True,
            capture_output=True,
        )
        _BUILDS[name] = out
    return _BUILDS[name]


def run(binary: Path, db: Path, home: Path) -> subprocess.CompletedProcess[str]:
    """The test build takes the radar home; the inbox is <home>/inbox, as in release."""
    return subprocess.run(
        [str(binary), str(db), str(home)], check=False, capture_output=True, text=True
    )


@unittest.skipUnless(ON_MAC, "needs macOS and swiftc")
class TestHelper(RadarCase):
    def setUp(self):
        super().setUp()
        self.plain = build("plain", [])
        self.db = self.tmp / "chat.db"
        con = sqlite3.connect(self.db)
        con.executescript((FIXTURES / "chat_db.sql").read_text())
        con.close()
        self.home = self.tmp / "radar"
        self.inbox = self.home / "inbox"

    def make_home(self):
        self.home.mkdir(mode=0o700)
        self.inbox.mkdir(mode=0o700)

    def records(self):
        lines = (self.inbox / "messages.jsonl").read_text().splitlines()
        return [json.loads(line) for line in lines]

    def test_exports_metadata_only(self):
        self.make_home()
        r = run(self.plain, self.db, self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        recs = self.records()
        chats = {c["chat"]: c["members"] for c in recs if c["type"] == "chat"}
        self.assertEqual(
            chats,
            {
                "iMessage;+;chat123": ["+14155550104", "bob@example.com"],
                "iMessage;-;+14155550101": ["+14155550101"],
            },
        )
        msgs = [m for m in recs if m["type"] == "message"]
        self.assertEqual([m["rowid"] for m in msgs], [1, 2, 4, 6])  # no tapback, no event
        self.assertTrue(all("text" not in m for m in msgs))
        self.assertIs(msgs[1]["from_me"], True)
        self.assertNotIn("sender", msgs[1])
        mode = stat.S_IMODE(os.stat(self.inbox / "messages.jsonl").st_mode)
        self.assertEqual(mode, 0o600)
        self.assertFalse((self.inbox / "messages.jsonl.tmp").exists())

    def test_snippet_build_truncates(self):
        self.make_home()
        r = run(build("snippets", ["-D", "RADAR_SNIPPETS"]), self.db, self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        texts = [m.get("text") for m in self.records() if m["type"] == "message"]
        self.assertEqual(texts[0], "hi there")
        self.assertEqual(len(texts[1]), 140)

    def test_refuses_symlinks_anywhere_on_the_path(self):
        real = self.tmp / "real"
        real.mkdir(mode=0o700)
        (real / "inbox").mkdir(mode=0o700)
        self.home.symlink_to(real)  # the radar home itself is a symlink
        r = run(self.plain, self.db, self.home)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("symlink", r.stderr)
        self.home.unlink()
        self.home.mkdir(mode=0o700)
        self.inbox.symlink_to(real / "inbox")  # the inbox is a symlink
        r = run(self.plain, self.db, self.home)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("symlink", r.stderr)
        self.assertEqual(list((real / "inbox").iterdir()), [])

    def test_refuses_group_writable_directories(self):
        for d in ("home", "inbox"):
            with self.subTest(d=d):
                self.make_home()
                getattr(self, d).chmod(0o770)
                r = run(self.plain, self.db, self.home)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("writable", r.stderr)
                shutil.rmtree(self.home)

    def test_unreadable_db_exits_77(self):
        self.make_home()
        r = run(self.plain, self.tmp / "missing.db", self.home)
        self.assertEqual(r.returncode, 77)
        self.assertIn("Full Disk Access", r.stderr)

    def test_export_feeds_the_imessage_source(self):
        r = run(self.plain, self.db, self.paths.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = run_source(self.con, IMessageSource(), SyncContext(self.paths, self.settings))
        self.assertEqual((res.status, res.rows_in), ("ok", 4))  # 1:1 both ways, 2 group received
        years = self.con.execute("SELECT DISTINCT year(ts) FROM interactions ORDER BY 1").fetchall()
        self.assertEqual(years, [(2016,), (2025,)])  # pre-10.13 seconds and nanoseconds
        self.assertFalse(self.paths.messages_export.exists())  # deleted once read


class TestApproval(RadarCase):
    """Only PJ, at a terminal, decides which source the FDA binary is built from."""

    def setUp(self):
        super().setUp()
        self.src = self.tmp / "radar-messages-export.swift"
        self.src.write_text(SOURCE.read_text())
        patcher = mock.patch.object(helper, "SOURCE", self.src)
        patcher.start()
        self.addCleanup(patcher.stop)

    def approve(self, answer="approve", interactive=True):
        out = StringIO()
        with redirect_stdout(out):
            ok = helper.approve(self.paths, ask=lambda _: answer, interactive=lambda: interactive)
        return ok, out.getvalue()

    def checks(self):
        return {c.name: c for c in doctor.helper_checks(self.paths)}

    def test_needs_a_terminal(self):
        with self.assertRaises(helper.NotApproved):
            self.approve(interactive=False)
        self.assertFalse(helper.approved_path(self.paths).exists())

    def test_anything_but_approve_declines(self):
        ok, _ = self.approve(answer="yes")
        self.assertFalse(ok)
        self.assertFalse(helper.approved_path(self.paths).exists())
        self.assertEqual(self.checks()["helper source"].level, "fail")

    def test_approve_then_a_change_shows_only_the_diff(self):
        ok, _ = self.approve()
        self.assertTrue(ok)
        self.assertEqual(self.checks()["helper source"].level, "ok")
        self.src.write_text(self.src.read_text() + "// a new line\n")
        self.assertEqual(self.checks()["helper source"].level, "warn")
        ok, out = self.approve(answer="")
        self.assertFalse(ok)
        self.assertIn("+// a new line", out)
        self.assertNotIn("import SQLite3", out)  # unchanged lines are not repeated
        self.assertNotEqual(
            helper.sha256(helper.approved_path(self.paths)), helper.sha256(self.src)
        )

    def test_build_refuses_without_approval(self):
        with self.assertRaises(helper.NotApproved):
            helper.build(self.paths)

    def test_build_uses_the_approved_copy_not_the_repo(self):
        self.approve()
        self.src.write_text(self.src.read_text() + "// unreviewed\n")
        with mock.patch.object(helper.subprocess, "run") as run_:
            helper.build(self.paths)
        swiftc, codesign = (c.args[0] for c in run_.call_args_list)
        self.assertEqual(swiftc[:2], ["/usr/bin/xcrun", "swiftc"])
        self.assertEqual(codesign[0], "/usr/bin/codesign")
        self.assertIn(str(helper.approved_path(self.paths)), swiftc)
        self.assertNotIn(str(self.src), swiftc)
        env = run_.call_args_list[0].kwargs["env"]
        self.assertEqual(env["PATH"], "/usr/bin:/bin:/usr/sbin:/sbin")
        self.assertFalse(any(k.startswith(("DYLD_", "DEVELOPER_DIR")) for k in env))
        state = helper.source_state(self.paths)
        self.assertEqual(state["built"], state["approved"])
        self.assertNotEqual(state["repo"], state["approved"])


if __name__ == "__main__":
    unittest.main()
