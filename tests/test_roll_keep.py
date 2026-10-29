import json
import re
import tempfile
import unittest
from collections import Counter
from pathlib import Path

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


class FakeGmail:
    account = "me@x"

    def __init__(self, ids):
        self._ids, self.relabels = ids, []

    def ids(self, query, cap=0):
        self.query = query
        return list(self._ids)

    def message(self, mid, headers=()):
        subject = {"m1": "Statement ready", "m2": "Sale ends", "m3": "Your order"}[mid]
        return {"id": mid, "threadId": f"t{mid}", "snippet": "x",
                "payload": {"headers": [{"name": "From", "value": f"S <{mid}@a.example.com>"},
                                        {"name": "Subject", "value": subject}]}}  # fmt: skip

    def relabel(self, *a, **kw):
        self.relabels.append(a)


class ByText:
    """A brain answering from a map of subject word -> class word."""

    def __init__(self, answers):
        self.answers = answers

    def think(self, system, user, temperature=None):
        return next((v for k, v in self.answers.items() if k in user), "unsure")


class FirstN:
    """A sample that keeps the ids in order."""

    def sample(self, ids, n):
        return ids[:n]


class ShadowTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.gmail = FakeGmail(["m1", "m2", "m3"])
        local = ByText({"Statement": "finance", "Sale": "promotion", "order": "promotion"})
        teacher = ByText({"Statement": "finance", "Sale": "promotion", "order": "receipts"})
        self.records = keep.shadow(self.gmail, local, teacher, "Roll/Updates", 10, self.root)

    def test_labels_nothing_and_records_both_answers(self):
        self.assertEqual(self.gmail.relabels, [])
        self.assertIn("-in:trash", self.gmail.query)
        self.assertEqual(len(self.records), 3)
        saved = list((self.root / "keep").glob("shadow-*.jsonl"))
        self.assertEqual(len(saved[0].read_text().splitlines()), 3)

    def test_a_crash_keeps_the_records_already_written(self):
        class Broken(ByText):
            def think(self, system, user, temperature=None):
                if "order" in user:
                    raise KeyboardInterrupt
                return super().think(system, user, temperature)

        root = self.root / "crash"
        brain = Broken({"Statement": "finance", "Sale": "promotion"})
        with self.assertRaises(KeyboardInterrupt):
            keep.shadow(FakeGmail(["m1", "m2", "m3"]), brain, None, "Roll/Updates", 10, root,
                        rng=FirstN())  # fmt: skip
        saved = next((root / "keep").glob("shadow-*.jsonl")).read_text().splitlines()
        self.assertEqual([json.loads(x)["id"] for x in saved], ["m1", "m2"])

    def test_pace_runs_before_each_email_and_can_stop_the_run(self):
        calls = []

        def pace():
            calls.append(1)
            if len(calls) == 3:
                raise RuntimeError("too hot")

        root = self.root / "paced"
        with self.assertRaisesRegex(RuntimeError, "too hot"):
            keep.shadow(FakeGmail(["m1", "m2", "m3"]), ByText({}), None, "Roll/Updates", 10,
                        root, rng=FirstN(), pace=pace)  # fmt: skip
        saved = next((root / "keep").glob("shadow-*.jsonl")).read_text().splitlines()
        self.assertEqual(len(saved), 2)

    def test_lost_keeps_and_disagreements(self):
        lost = keep.lost_keeps(self.records)
        self.assertEqual([r["id"] for r in lost], ["m3"])
        dis = (self.root / "keep" / "disagreements.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(x)["id"] for x in dis], ["m3"])

    def test_summary_counts_agreement_and_lost_keeps(self):
        text = keep.summary(self.records, "Roll/Updates")
        self.assertIn("2/3", text)
        self.assertIn("Discard where the teacher keeps: 1", text)
        self.assertIn("Your order (discard/promotion vs keep/receipts)", text)

    def test_fixture_candidates_once_each_labelled_by_the_teacher(self):
        rewriter = FakeBrain('{"id": "keep/receipts order note", "from": "a", "subject": "b"}')
        made, personal = keep.fixture_candidates(self.root, rewriter)
        self.assertEqual([(f["id"], f["label"], f["student_label"]) for f in made],
                         [("keep_receipts_order_note", "keep/receipts", "discard/promotion")])  # fmt: skip
        self.assertEqual(personal, 0)
        self.assertEqual(keep.fixture_candidates(self.root, rewriter), ([], 0))
