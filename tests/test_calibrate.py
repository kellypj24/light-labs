import importlib.util
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from light_labs.core import calibrate, decide

HAS_SKLEARN = importlib.util.find_spec("sklearn") is not None


def overconfident(n, seed=3):
    """Raw p 0.55-0.97; the truth is far less sure."""
    rnd = random.Random(seed)
    ps = [rnd.uniform(0.55, 0.97) for _ in range(n)]
    return ps, [rnd.random() < 0.25 + 0.4 * (p - 0.55) / 0.42 for p in ps]


class ApplyTest(unittest.TestCase):
    def test_identity_and_none_pass_through(self):
        self.assertEqual(calibrate.apply(None, 0.7), 0.7)
        self.assertEqual(calibrate.apply({"method": "identity"}, 0.7), 0.7)

    def test_platt_is_monotone(self):
        m = {"method": "platt", "a": 0.8, "b": -0.5}
        out = [calibrate.apply(m, p) for p in (0.1, 0.5, 0.9)]
        self.assertEqual(out, sorted(out))
        self.assertLess(out[2], 0.9)

    def test_isotonic_interpolates_and_clips(self):
        m = {"method": "isotonic", "x": [0.2, 0.6, 0.9], "y": [0.1, 0.3, 0.5]}
        self.assertEqual(calibrate.apply(m, 0.0), 0.1)
        self.assertEqual(calibrate.apply(m, 1.0), 0.5)
        self.assertAlmostEqual(calibrate.apply(m, 0.4), 0.2)

    def test_scores(self):
        self.assertEqual(calibrate.brier([1.0, 0.0], [1, 0]), 0.0)
        self.assertAlmostEqual(calibrate.ece([0.9] * 10, [1] * 5 + [0] * 5), 0.4)


class FitTest(unittest.TestCase):
    def test_too_few_and_one_class_stay_identity(self):
        self.assertEqual(calibrate.fit([0.9] * 10, [1] * 10)["status"], "too-few")
        self.assertEqual(calibrate.fit([0.9] * 40, [1] * 40)["status"], "one-class")

    @unittest.skipUnless(HAS_SKLEARN, "needs the analytics dependency group")
    def test_platt_below_the_isotonic_floor_and_it_must_beat_raw(self):
        m = calibrate.fit(*overconfident(80))
        self.assertEqual((m["method"], m["status"]), ("platt", "fitted"))
        self.assertLess(m["brier_cal"], m["brier_raw"])
        self.assertLess(calibrate.apply(m, 0.9), 0.9)

    @unittest.skipUnless(HAS_SKLEARN, "needs the analytics dependency group")
    def test_isotonic_from_the_floor(self):
        m = calibrate.fit(*overconfident(calibrate.PLATT_MAX + 50))
        self.assertEqual(m["method"], "isotonic")

    @unittest.skipUnless(HAS_SKLEARN, "needs the analytics dependency group")
    def test_already_calibrated_keeps_identity(self):
        rnd = random.Random(5)
        ps = [rnd.random() for _ in range(120)]
        m = calibrate.fit(ps, [rnd.random() < p for p in ps])
        self.assertIn(m["status"], ("no-gain", "fitted"))
        if m["status"] == "no-gain":
            self.assertEqual(m["method"], "identity")


class PairsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.var = Path(tmp.name)

    def item(self, bucket, n, verdict, roll):
        path = self.var / "roll" / "queue" / bucket / f"i{n}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "kind": "dependabot", "created": "2026-10-30T00:00:00+00:00", "roll": roll,
            "target": {"repo": "kellypj24/scouter", "pr": n, "head": "abcdef123"},
            "big_brother": {"model": "sonnet", "verdict": verdict},
        }))  # fmt: skip

    def test_chores_pairs_use_raw_p_and_skip_fixtures(self):
        self.item("sent", 1, "MERGE", {"p_yes": 0.4, "p_raw": 0.9, "brain": "ollama:x"})
        self.item("rejected", 2, "HOLD", {"p_yes": 0.8})
        self.item("sent", 3, "MERGE", {"p_yes": 0.8, "brain": "ollama:x"})
        with mock.patch.object(calibrate, "fixture_ids", return_value={"scouter_3"}):
            pairs = calibrate.collect(self.var)
        self.assertEqual(
            sorted((p["source_id"], p["p"], p["label"], p["brain"]) for p in pairs),
            [("kellypj24/scouter#1@abcdef1", 0.9, True, "ollama:x"),
             ("kellypj24/scouter#2@abcdef1", 0.8, False, None)],
        )  # fmt: skip
        self.assertEqual(pairs[0]["label_by"], "claude:sonnet")

    def test_pair_files_are_collected_and_brainless_pairs_never_fit(self):
        path = self.var / "roll" / "pairs" / "deps.jsonl"
        path.parent.mkdir(parents=True)
        rows = [{"robot": "roll", "question": "deps", "brain": None, "p": 0.5, "label": True}]
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        pairs = calibrate.collect(self.var)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(calibrate.fit_all(pairs), [])

    def test_stage_fixture_ids_are_read(self):
        self.assertIn("data_engineering_242", calibrate.fixture_ids("dependabot-merge"))


class LookupTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(calibrate.config, "VAR", Path(tmp.name))
        patch.start()
        self.addCleanup(patch.stop)
        calibrate.MAPS = None

    def test_no_file_no_map(self):
        self.assertIsNone(calibrate.lookup("ollama:x", "q"))

    def test_ask_applies_the_map_and_keeps_raw(self):
        m = {"robot": "roll", "question": "q", "brain": "ollama:x", "method": "platt",
             "a": 1.0, "b": -2.0, "status": "fitted"}  # fmt: skip
        calibrate.export([m])

        class Local:
            model = "x"

            def choose(self, system, user, choices, num_ctx=None):
                return {"yes": 0.8, "no": 0.2}

        a = decide.ask(Local(), "state", "question?", key="q")
        self.assertEqual(a.raw, {"yes": 0.8, "no": 0.2})
        self.assertAlmostEqual(a.p(), calibrate.apply(m, 0.8))
        self.assertEqual(a.choice, "no")  # 0.8 raw is about 0.35 calibrated
        self.assertEqual(decide.ask(Local(), "state", "question?").p(), 0.8)  # no key, raw


if __name__ == "__main__":
    unittest.main()
