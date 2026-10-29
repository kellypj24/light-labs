import json
import tempfile
import unittest
from pathlib import Path

from light_labs.agents.roll import keep, sanitize

# Invented, but shaped like the real thing; none of these may reach the rewriter.
RAW = (
    "Dana Whitfield", "dana.whitfield", "Whitfield", "4417 1234 5678 9010", "$1,204.18",
    "614-555-0142", "dana@whitfield-family.example.com", "https://track.example.com/a?b=9",
    "1Z999AA10123456784", "Marisol", "BOTWCOLUMBUS", "guest.pal",
)  # fmt: skip

DISAGREEMENTS = [
    {"id": "m1", "from": '"Dana Whitfield" <dana.whitfield@bank.example.com>',
     "subject": "Dana, your card 4417 1234 5678 9010 statement",
     "snippet": "Balance $1,204.18. Questions? Call 614-555-0142 or dana@whitfield-family.example.com",
     "category": "updates", "unsubscribe": False,
     "local": "discard/marketing", "teacher": "keep/finance", "agree": False},
    {"id": "m2", "from": "Shipping <ship@carrier.example.net>",
     "subject": "Package 1Z999AA10123456784 delivered",
     "snippet": "Track at https://track.example.com/a?b=9", "category": None,
     "unsubscribe": True, "local": "discard/notification", "teacher": "keep/receipts",
     "agree": False},
    {"id": "m3", "from": "Marisol <guest.pal@gmail.com>", "subject": "Re: [BOTWCOLUMBUS] Saturday",
     "snippet": "See you there", "category": "forums", "unsubscribe": True,
     "local": "discard/notification", "teacher": "keep/people", "agree": False},
]  # fmt: skip


class Recorder:
    def __init__(self):
        self.prompts = []

    def think(self, system, user, temperature=None):
        self.prompts.append(user)
        return json.dumps({"id": "fx", "from": "a@example.org", "subject": "s"})


class SanitizeTest(unittest.TestCase):
    def test_personal_senders(self):
        for addr in ("a@gmail.com", "b@yahoo.co.uk", "c@icloud.com", "d@outlook.com", "e@pm.me"):
            self.assertTrue(sanitize.is_personal({"from": addr}), addr)
        for addr in ("a@bank.example.com", "b@gmail.example.com", "", "Shop <noreply@shop.com>"):
            self.assertFalse(sanitize.is_personal({"from": addr}), addr)

    def test_view_refuses_personal_mail(self):
        with self.assertRaises(ValueError):
            sanitize.view(DISAGREEMENTS[2])

    def test_scrub_placeholders(self):
        self.assertEqual(
            sanitize.scrub("Dana: $1,204.18, card 4417 1234 5678 9010, (614) 555-0142", ["Dana"]),
            "<name>: <amount>, card <number>, <phone>",
        )
        self.assertEqual(sanitize.scrub("Order 12345 for 3 items"), "Order <number> for 3 items")

    def test_fixture_rewriter_never_sees_raw_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "keep").mkdir()
            (root / "keep" / "disagreements.jsonl").write_text(
                "".join(json.dumps(d) + "\n" for d in DISAGREEMENTS)
            )
            rewriter = Recorder()
            made, personal = keep.fixture_candidates(root, rewriter)
        self.assertEqual((len(made), personal), (2, 1))
        sent = "\n".join(rewriter.prompts)
        for raw in RAW:
            self.assertNotIn(raw.lower(), sent.lower(), raw)
        self.assertIn("bank.example.com", sent)
        self.assertIn("<amount>", sent)
