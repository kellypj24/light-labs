import json
import tempfile
import unittest
from pathlib import Path

from light_labs.evals import results


def sample(fixture, passed, n=1, **extra):
    return {
        "contestant": "mega-man",
        "role": "mega-man",
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

    def count(self, sql):
        with results.connect(self.db) as con:
            return con.execute(sql).fetchone()[0]

    def test_ingest_is_idempotent(self):
        stamp = {"run_id": "reply-draft-1", "commit": "abc1234", "dirty": False}
        path = self.write(
            "reply-draft-1.jsonl",
            [sample("chat_a", True, 1, **stamp), sample("chat_a", False, 2, **stamp)],
        )
        self.assertEqual(results.ingest([path], db=self.db), {"reply-draft-1": 2})
        results.ingest([path], db=self.db)
        self.assertEqual(self.count("SELECT count(*) FROM raw.eval_samples"), 2)
        self.assertEqual(
            self.count("SELECT any_value(source) FROM raw.eval_samples"), "reply-draft-1.jsonl"
        )

    def test_older_files_use_their_file_name_as_run_id(self):
        path = self.write("reply-draft-20261012T172107Z.jsonl", [sample("chat_a", True)])
        self.assertEqual(results.ingest([path], db=self.db), {"reply-draft-20261012T172107Z": 1})
        self.assertIsNone(self.count('SELECT any_value("commit") FROM raw.eval_samples'))

    def test_new_columns_migrate_into_an_old_table(self):
        import duckdb

        with duckdb.connect(str(self.db)) as con:
            con.execute("CREATE SCHEMA raw")
            con.execute("CREATE TABLE raw.eval_samples (run_id VARCHAR, source VARCHAR NOT NULL)")
        path = self.write("r.jsonl", [sample("chat_a", True, run_id="r", filter="chat")])
        results.ingest([path], db=self.db)
        self.assertEqual(self.count('SELECT any_value("filter") FROM raw.eval_samples'), "chat")

    def test_runs_needs_the_dbt_marts(self):
        with self.assertRaisesRegex(LookupError, "just analytics"):
            results.runs(db=self.db)


if __name__ == "__main__":
    unittest.main()
