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
from pathlib import Path

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


def run(binary: Path, db: Path, inbox: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(binary), str(db), str(inbox)], check=False, capture_output=True, text=True
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
        self.inbox = self.tmp / "inbox"

    def records(self):
        lines = (self.inbox / "messages.jsonl").read_text().splitlines()
        return [json.loads(line) for line in lines]

    def test_exports_metadata_only(self):
        self.inbox.mkdir(mode=0o700)
        r = run(self.plain, self.db, self.inbox)
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
        self.inbox.mkdir(mode=0o700)
        r = run(build("snippets", ["-D", "RADAR_SNIPPETS"]), self.db, self.inbox)
        self.assertEqual(r.returncode, 0, r.stderr)
        texts = [m.get("text") for m in self.records() if m["type"] == "message"]
        self.assertEqual(texts[0], "hi there")
        self.assertEqual(len(texts[1]), 140)

    def test_refuses_symlinked_inbox(self):
        real = self.tmp / "real"
        real.mkdir(mode=0o700)
        self.inbox.symlink_to(real)
        r = run(self.plain, self.db, self.inbox)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("symlink", r.stderr)
        self.assertEqual(list(real.iterdir()), [])

    def test_refuses_group_writable_inbox(self):
        self.inbox.mkdir()
        self.inbox.chmod(0o770)
        r = run(self.plain, self.db, self.inbox)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("writable", r.stderr)

    def test_unreadable_db_exits_77(self):
        self.inbox.mkdir(mode=0o700)
        r = run(self.plain, self.tmp / "missing.db", self.inbox)
        self.assertEqual(r.returncode, 77)
        self.assertIn("Full Disk Access", r.stderr)

    def test_export_feeds_the_imessage_source(self):
        r = run(self.plain, self.db, self.paths.inbox)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = run_source(self.con, IMessageSource(), SyncContext(self.paths, self.settings))
        self.assertEqual((res.status, res.rows_in), ("ok", 4))  # 1:1 both ways, 2 group received
        years = self.con.execute("SELECT DISTINCT year(ts) FROM interactions ORDER BY 1").fetchall()
        self.assertEqual(years, [(2016,), (2025,)])  # pre-10.13 seconds and nanoseconds


if __name__ == "__main__":
    unittest.main()
