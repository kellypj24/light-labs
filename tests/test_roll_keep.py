import re
import unittest
from collections import Counter

from light_labs import config
from light_labs.agents.roll import keep

STAGE = config.REPO / "evals" / "stages" / "mail-keep.yaml"


class FakeBrain:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def think(self, system, user, temperature=None):
        self.calls.append(user)
        return self.answer


class ParseTest(unittest.TestCase):
    def test_keep_and_discard_classes(self):
        self.assertEqual(keep.parse_label("finance"), "keep/finance")
        self.assertEqual(keep.parse_label("Class: Job-Alert."), "discard/job-alert")
        self.assertEqual(keep.parse_label("legal tax"), "keep/legal-tax")

    def test_first_class_word_wins(self):
        self.assertEqual(keep.parse_label("promotion, though it mentions finance"),
                         "discard/promotion")  # fmt: skip

    def test_no_class_word_is_none(self):
        self.assertIsNone(keep.parse_label("I'm not sure"))


class ClassifyTest(unittest.TestCase):
    def test_one_call_with_the_email(self):
        brain = FakeBrain("receipts")
        out = keep.classify(brain, {"from": "Shop <o@shop.example.com>", "subject": "Shipped"})
        self.assertEqual(out["label"], "keep/receipts")
        self.assertEqual(len(brain.calls), 1)
        self.assertIn("Shipped", brain.calls[0])

    def test_an_unparsed_answer_keeps_the_mail(self):
        out = keep.classify(FakeBrain("Thanks, good to hear from you."), {"subject": "x"})
        self.assertEqual((out["label"], out["by"]), (keep.UNSURE, "model-unparsed"))


class FixturesTest(unittest.TestCase):
    """The stage's fixtures: plan floor of 40, at least 3 per class, valid labels."""

    def setUp(self):
        text = STAGE.read_text()
        self.ids = re.findall(r"^  - id: (\S+)", text, re.MULTILINE)
        self.labels = re.findall(r"expect: \{label: (\S+?)\}", text)

    def test_counts(self):
        self.assertGreaterEqual(len(self.ids), 40)
        self.assertEqual(len(self.ids), len(set(self.ids)))
        self.assertEqual(len(self.labels), len(self.ids))

    def test_every_label_is_a_class_with_three_fixtures(self):
        valid = {f"keep/{c}" for c in keep.KEEP} | {f"discard/{c}" for c in keep.DISCARD}
        self.assertEqual(set(self.labels) - valid, set())
        thin = {lab: n for lab, n in Counter(self.labels).items() if n < 3}
        self.assertEqual(thin, {})
        self.assertEqual(valid - set(self.labels), set())
