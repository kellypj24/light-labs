import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from light_labs.core import brain
from light_labs.evals import run_one

MEMORY = "# What Rush knows\n- Rush runs on a local model."


def envelope(payload):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        run_one.main(["--input-json", json.dumps(payload)])
    return json.loads(out.getvalue())


class BrainForTest(unittest.TestCase):
    def test_specs(self):
        self.assertIsInstance(brain.brain_for("ollama:llama3.1:8b"), brain.Brain)
        self.assertEqual(brain.brain_for("ollama:llama3.1:8b").model, "llama3.1:8b")
        self.assertIsInstance(brain.brain_for("claude:sonnet"), brain.ClaudeCLI)
        self.assertIsInstance(brain.brain_for("mock"), brain.Mock)
        for bad in ("ollama", "claude:", "gpt:4", ""):
            with self.subTest(spec=bad), self.assertRaises(ValueError):
                brain.brain_for(bad)

    def test_mock_escalates_work_only(self):
        m = brain.Mock()
        self.assertTrue(
            m.think("s", "<message>\nplease write a script\n</message>").startswith("ESCALATE:")
        )
        self.assertFalse(m.think("s", "<message>\nthanks!\n</message>").startswith("ESCALATE:"))

    def test_claude_cli_isolation_flag(self):
        done = mock.Mock(
            returncode=0,
            stdout=json.dumps(
                {"result": "hi", "total_cost_usd": 0.01, "usage": {"input_tokens": 5}}
            ),
        )
        with mock.patch("subprocess.run", return_value=done) as run:
            with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}):
                b = brain.ClaudeCLI("sonnet")
                self.assertEqual(b.think("sys", "user"), "hi")
            self.assertIn("--bare", run.call_args.args[0])
            self.assertTrue(b.last["isolated"])
            self.assertEqual(b.last["cost_usd"], 0.01)
            with mock.patch.dict("os.environ", {}, clear=True):
                b.think("sys", "user")
            self.assertNotIn("--bare", run.call_args.args[0])
            self.assertFalse(b.last["isolated"])

    def test_claude_cli_errors(self):
        failed = mock.Mock(returncode=1, stdout="", stderr="not logged in")
        with mock.patch("subprocess.run", return_value=failed), self.assertRaises(RuntimeError):
            brain.ClaudeCLI("sonnet").think("s", "u")


class RunOneTest(unittest.TestCase):
    def test_reply_draft_with_mock(self):
        out = envelope(
            {
                "stage": "reply-draft",
                "brain": "mock",
                "memory": MEMORY,
                "input": {"sender": "alpha", "content": "Can you review this code?"},
            }
        )
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["result"]["escalate"], "mock work request")
        self.assertNotIn("ESCALATE", out["result"]["draft"])

    def test_comment_kind(self):
        out = envelope(
            {
                "stage": "reply-draft",
                "brain": "mock",
                "memory": MEMORY,
                "input": {
                    "kind": "comment",
                    "sender": "alpha",
                    "title": "T",
                    "content": "nice",
                    "earlier": [{"author": "bravo", "text": "first"}],
                },
            }
        )
        self.assertTrue(out["ok"], out)
        self.assertIsNone(out["result"]["escalate"])

    def test_errors_come_back_in_the_envelope(self):
        out = envelope({"stage": "nope", "brain": "mock", "input": {}})
        self.assertFalse(out["ok"])
        self.assertIn("unknown stage", out["error"])
        out = envelope({"stage": "reply-draft", "brain": "gpt:4", "input": {}})
        self.assertFalse(out["ok"])

    def test_uses_rushs_real_prompt_with_fixture_memory(self):
        seen = {}

        class Spy(brain.Mock):
            def think(self, system, user, temperature=None):
                seen["system"], seen["user"] = system, user
                return super().think(system, user)

        with mock.patch.object(run_one, "brain_for", return_value=Spy()):
            run_one.run(
                {
                    "stage": "reply-draft",
                    "brain": "mock",
                    "memory": MEMORY,
                    "input": {"sender": "alpha", "summary": "hi", "content": "hello"},
                }
            )
        self.assertIn("You are Rush (DLN-100)", seen["system"])
        self.assertIn("Rush runs on a local model.", seen["system"])
        self.assertIn("## agent-net-etiquette", seen["system"])
        self.assertIn("<message>\nhello\n</message>", seen["user"])


if __name__ == "__main__":
    unittest.main()
