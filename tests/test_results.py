import json
import tempfile
import unittest
from pathlib import Path

from light_labs.evals import results


def sample(fixture, passed, n=1, **extra):
    return {
        "contestant": "rock",
        "role": "rock",
        "brain": "ollama:llama3.1:8b",
        "stage": "reply-draft",
        "fixture": fixture,
        "category": fixture.split("_")[0],
        "sample": n,
        "passed": passed,
        "checks": [{"name": "ran", "passed": True}],
        "draft": "hi",
        "latency_s": 1.0,
        "cost_usd": 0,
        "at": "2026-10-12T17:21:07Z",
        **extra,
    }


class ResultsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = self.dir / "lab.duckdb"

    def write(self, name, rows):
        path = self.dir / name
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return path

    def test_ingest_is_idempotent_and_rates_add_up(self):
        stamp = {"run_id": "reply-draft-1", "commit": "abc1234", "dirty": False}
        path = self.write(
            "reply-draft-1.jsonl",
            [
                sample("chat_a", True, 1, **stamp),
                sample("chat_a", False, 2, **stamp),
                sample("work_b", True, 1, **stamp),
                sample("work_b", True, 2, **stamp),
            ],
        )
        self.assertEqual(results.ingest([path], db=self.db), {"reply-draft-1": 4})
        results.ingest([path], db=self.db)
        cols, rows = results.runs(db=self.db)
        run = dict(zip(cols, rows[0], strict=True))
        self.assertEqual(len(rows), 1)
        self.assertEqual(run["samples"], 4)
        self.assertEqual(run["pass_rate"], 0.75)
        self.assertEqual(run["fixture_rate"], 0.5)  # chat_a failed one sample
        self.assertEqual(run["commit"], "abc1234")

    def test_older_files_use_their_file_name_as_run_id(self):
        path = self.write("reply-draft-20261012T172107Z.jsonl", [sample("chat_a", True)])
        self.assertEqual(
            results.ingest([path], db=self.db), {"reply-draft-20261012T172107Z": 1}
        )
        cols, rows = results.runs(contestant="rock", db=self.db)
        self.assertIsNone(dict(zip(cols, rows[0], strict=True))["commit"])
        self.assertEqual(results.runs(contestant="bass", db=self.db)[1], [])


if __name__ == "__main__":
    unittest.main()
