import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from light_labs.core import claude_results


def write(path, records, tail=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records) + tail)


class ClaudeResultsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db = self.root / "lab.duckdb"

    def rows(self, sql):
        from light_labs.evals import results

        with results.connect(self.db) as con:
            return con.execute(sql).fetchall()

    def test_ingest_appends_new_lines_once_across_live_and_archive(self):
        live, archive = self.root / "live", self.root / "archive"
        a = {"type": "user", "sessionId": "s1", "uuid": "u1"}
        b = {"type": "assistant", "sessionId": "s1", "uuid": "a1"}
        write(live / "-w-app/s1.jsonl", [a], tail='{"type": "assist')  # cut off mid-write
        write(archive / "-w-app/s1.jsonl", [a])
        write(live / "-w-app/s1/subagents/agent-x.jsonl", [b])
        self.assertEqual(claude_results.ingest([live, archive], db=self.db), (2, 2))
        write(live / "-w-app/s1.jsonl", [a, {**b, "uuid": "a2"}])
        self.assertEqual(claude_results.ingest([live, archive], db=self.db), (1, 3))
        got = self.rows(
            "SELECT project_dir, transcript FROM raw.claude_records ORDER BY transcript"
        )
        self.assertEqual(
            got,
            [
                ("-w-app", "s1.jsonl"),
                ("-w-app", "s1.jsonl"),
                ("-w-app", "s1/subagents/agent-x.jsonl"),
            ],
        )

    def test_ingest_keeps_records_after_the_transcript_is_deleted(self):
        live = self.root / "live"
        write(live / "-w-app/s1.jsonl", [{"type": "user", "uuid": "u1"}])
        claude_results.ingest([live], db=self.db)
        (live / "-w-app/s1.jsonl").unlink()
        self.assertEqual(claude_results.ingest([live], db=self.db), (0, 1))

    def test_redact_hides_each_kind_and_keeps_json_valid(self):
        bot, hexed = "1234567890:AA" + "b" * 33, "a1" * 24
        cmd = f"security add-generic-password -U -s svc -a me -w '{bot}' && echo {hexed}"
        line = json.dumps({"type": "user", "message": {"content": cmd}})
        out = claude_results.redact(line)
        self.assertNotIn(bot, out)
        self.assertNotIn(hexed, out)
        self.assertIn("-w [REDACTED:keychain]", out)
        self.assertIn("[REDACTED:token]", out)
        json.loads(out)
        self.assertEqual(
            claude_results.redact('{"sha": "' + "c" * 64 + '"}'), '{"sha": "' + "c" * 64 + '"}'
        )

    def test_ingest_redacts_new_lines_stored_rows_and_archive(self):
        secret = "sk-ant-" + "k" * 30
        live = self.root / "live"
        record = {"type": "user", "uuid": "u1", "message": {"content": f"key {secret}"}}
        write(live / "-w-app/s1.jsonl", [record])
        with mock.patch.object(claude_results, "redact", lambda line: line):
            claude_results.ingest([live], db=self.db)  # a row stored before redaction existed
        self.assertIn(
            secret, self.rows("SELECT CAST(record AS VARCHAR) FROM raw.claude_records")[0][0]
        )
        archive = self.root / "var" / "claude" / "projects"
        write(archive / "-w-app/s0.jsonl", [record])
        with (
            mock.patch.object(claude_results.config, "VAR", self.root / "var"),
            mock.patch.object(claude_results, "project_dirs", lambda: [live]),
        ):
            self.assertEqual(claude_results.ingest(db=self.db), (0, 1))
        (text,) = self.rows("SELECT CAST(record AS VARCHAR) FROM raw.claude_records")[0]
        self.assertNotIn(secret, text)
        self.assertIn("[REDACTED:anthropic]", text)
        self.assertNotIn(secret, (archive / "-w-app/s0.jsonl").read_text())
        self.assertIn(secret, (live / "-w-app/s1.jsonl").read_text())  # Claude Code's own file

    def test_ingest_with_nothing_there(self):
        self.assertEqual(claude_results.ingest([self.root / "none"], db=self.db), (0, 0))


if __name__ == "__main__":
    unittest.main()
