import tempfile
import unittest
from pathlib import Path

from light_labs.core import queue_results
from light_labs.core.store import Store


class QueueResultsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db = self.root / "lab.duckdb"
        self.store = Store(self.root / "rush")

    def rows(self, sql):
        from light_labs.evals import results

        with results.connect(self.db) as con:
            return con.execute(sql).fetchall()

    def test_enqueue_keeps_the_original_draft_and_what_produced_it(self):
        item = self.store.enqueue(
            "reply",
            {"to": ["nova"]},
            "hi",
            "nova: hello",
            brain="ollama:llama3.1:8b",
            commit="abc1234",
            dirty=False,
        )
        self.assertEqual(item["drafted"], "hi")
        self.assertEqual((item["brain"], item["commit"]), ("ollama:llama3.1:8b", "abc1234"))

    def test_ingest_reloads_every_bucket(self):
        a = self.store.enqueue("reply", {"to": ["nova"]}, "hi", "c", escalate="do work")
        b = self.store.enqueue("comment", {"task_id": "t1"}, "no", "c")
        self.store.enqueue("reply", {"to": ["quill"]}, "later", "c")
        self.store.resolve(a["id"], "sent", result_id="obj1")
        self.store.resolve(b["id"], "rejected", reason="invented a link")
        self.assertEqual(queue_results.ingest(self.root, db=self.db), {"rush": 3})
        queue_results.ingest(self.root, db=self.db)  # a full reload, not an append
        rows = self.rows("SELECT status, escalation, reason FROM raw.queue_items")
        got = {status: (esc, reason) for status, esc, reason in rows}
        self.assertEqual(got["sent"], ("do work", None))
        self.assertEqual(got["rejected"], (None, "invented a link"))
        self.assertIn("pending", got)
        self.assertEqual(self.rows("SELECT count(*) FROM raw.queue_items")[0][0], 3)

    def test_ingest_with_no_queues(self):
        self.assertEqual(queue_results.ingest(self.root / "empty", db=self.db), {})


if __name__ == "__main__":
    unittest.main()
