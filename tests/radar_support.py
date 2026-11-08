"""Radar test support. Synthetic fixtures only: fictional 415-555-01xx numbers and example.* domains."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from light_labs.radar.config import Paths, Settings
from light_labs.radar.db import connect
from light_labs.radar.normalize import APPLE_EPOCH

FIXTURES = Path(__file__).parent / "fixtures" / "radar"
AS_OF = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)

CHATS = {
    "c_alice": ["+14155550101"],
    "c_bob": ["bob@example.com"],
    "c_carol": ["+14155550103"],
    "c_group": ["+14155550104", "+14155550108"],
    "c_unknown": ["+14155550199"],
    "c_short": ["12345"],
}


def apple_ns(dt: datetime) -> int:
    return int((dt - APPLE_EPOCH).total_seconds() * 1_000_000_000)


def timeline() -> list[dict]:
    """Messages as the helper exports them. Days are counted back from AS_OF."""
    msgs: list[tuple[str, int, bool, str | None]] = []  # chat, days_ago, from_me, sender

    def two_way(chat: str, handle: str, days: int) -> None:
        msgs.append((chat, days, False, handle))
        msgs.append((chat, days, True, None))

    for k in range(100):  # Alice: weekly two-way, last 20 days ago
        two_way("c_alice", "+14155550101", 20 + 7 * k)
    for days in range(40, 400, 45):  # Bob: every 45 days, last 40 days ago
        two_way("c_bob", "bob@example.com", days)
    for days in range(70, 420, 30):  # Carol: monthly, then quiet for 70 days
        two_way("c_carol", "+14155550103", days)
    for days in range(5, 365, 10):  # Dan: group only
        two_way("c_group", "+14155550104", days)
    for days in (3, 4, 9):  # an unknown number, never answered
        msgs.append(("c_unknown", days, False, "+14155550199"))
    msgs.append(("c_short", 2, False, "12345"))

    out = []
    for i, (chat, days, from_me, sender) in enumerate(sorted(msgs, key=lambda m: -m[1]), 1):
        ts = AS_OF - timedelta(days=days) + (timedelta(hours=1) if from_me else timedelta())
        out.append(
            {
                "type": "message",
                "rowid": i,
                "guid": f"g{i}",
                "from_me": from_me,
                "date": apple_ns(ts),
                "sender": sender,
                "chat": chat,
                "service": "SMS" if chat == "c_carol" else "iMessage",
                "text": f"message {i} " + "x" * 200,
            }
        )
    return out


def write_export(path: Path, messages: list[dict]) -> None:
    chats = [{"type": "chat", "chat": c, "members": m} for c, m in CHATS.items()]
    path.write_text("".join(json.dumps(r) + "\n" for r in chats + messages))


class RadarCase(unittest.TestCase):
    """A fresh RADAR_HOME per test: the contacts fixture, a helper export, circles, config."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        p = Paths(self.tmp / "home")
        p.ensure()
        shutil.copy(FIXTURES / "contacts.vcf", p.contacts_dir / "contacts.vcf")
        write_export(p.messages_export, timeline())
        p.circles.write_text(
            "people:\n"
            '  "Alice Inner": inner\n'
            '  "bob@example.com": close\n'
            '  "Carol Cooling": {circle: close}\n'
            '  "+1 (415) 555-0104": friends\n'
        )
        p.config.write_text(
            "former_employers: [SmarterDx, THP, Arine]\noutput_dir: "
            + str(self.tmp / "drive")
            + "\n"
        )
        self.paths = p
        self.settings = Settings.load(p)
        self.con = connect(p.db)
        self.addCleanup(self.con.close)
