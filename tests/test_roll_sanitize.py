import json
import tempfile
import unittest
from pathlib import Path

from light_labs.agents.roll import keep, sanitize

# Invented, but shaped like the real thing; none of these may reach the rewriter.
RAW = (
    "1,204.18", "Dana Whitfield", "dana.whitfield", "Whitfield", "4417 1234 5678 9010",
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

    def test_vanity_domains_are_personal_brands_are_not(self):
        self.assertTrue(sanitize.is_personal({"from": "Dana Whitfield <dana@whitfield.net>"}))
        self.assertTrue(sanitize.is_personal({"from": "a@privaterelay.appleid.com"}))
        for sender in ("Google Security <no-reply@accounts.google.com>",
                       "Chase <alerts@chase.com>", "Orders <orders@shop.example.com>"):  # fmt: skip
            self.assertFalse(sanitize.is_personal({"from": sender}), sender)

    def test_scrub_placeholders(self):
        self.assertEqual(
            sanitize.scrub("Dana: $1,204.18, card 4417 1234 5678 9010, (614) 555-0142", ["dana"]),
            "<name>: <amount>, card <number>, <phone>",
        )
        self.assertEqual(sanitize.scrub("Order 12345 for 3 items"), "Order <number> for 3 items")
        self.assertEqual(
            sanitize.scrub("Balance: 1,204.18, USD 88, due 3.50, rooms 12 - 15"),
            "Balance: <amount>, <amount>, due <amount>, rooms 12 - 15",
        )
        self.assertEqual(sanitize.scrub("Track 1Z999AA10123456784"), "Track <id>")
        self.assertEqual(sanitize.scrub("call (614) 555-0142", ["phone"]), "call <phone>")

    def test_signal_words_in_the_sender_name_survive(self):
        v = sanitize.view({"from": "Google Security <security@accounts.google.com>",
                           "subject": "Security alert for Google Account"})  # fmt: skip
        self.assertEqual(v["subject"], "Security alert for <name> Account")

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
