import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from light_labs import config
from light_labs.core import brain, gate

PACKAGE = Path(__file__).resolve().parents[1] / "light_labs"


def modules():
    for path in sorted(PACKAGE.rglob("*.py")):
        yield path, ast.parse(path.read_text())


def calls(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if (isinstance(f, ast.Name) and f.id == name) or (
                isinstance(f, ast.Attribute) and f.attr == name
            ):
                yield node


def runs_claude(node):
    """subprocess.run/Popen(["claude", ...])"""
    if not (isinstance(node.func, ast.Attribute) and node.func.attr in ("run", "Popen")):
        return False
    first = node.args[0] if node.args else None
    return (
        isinstance(first, ast.List)
        and first.elts
        and isinstance(first.elts[0], ast.Constant)
        and first.elts[0].value == "claude"
    )


class GateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.var = Path(tmp.name)
        patch = mock.patch.object(gate.config, "VAR", self.var)
        patch.start()
        self.addCleanup(patch.stop)

    def rows(self):
        log = self.var / "gate" / "verdicts.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()]

    def test_client_repo_denied_from_day_one(self):
        for text in ("see ~/recoup/rules.py", "kellypj24/dentasys-modernization#3"):
            with self.subTest(text=text), self.assertRaises(gate.Denied):
                gate.check("roll/chores", "s", text)
        self.assertTrue(all(r["blocked"] for r in self.rows()))
        self.assertNotIn("recoup", json.dumps(self.rows()))  # no payload in the record

    def test_client_repo_cwd_denied(self):
        with tempfile.TemporaryDirectory() as home:
            repo = Path(home) / "recoup"
            repo.mkdir()
            with self.assertRaises(gate.Denied):
                gate.check("roll/chores", "s", "u", "Read,Grep,Glob", str(repo))

    def test_other_rules_record_without_blocking(self):
        v = gate.check("rush/auto", "notes", "Dana <dana@gmail.com> asked", "Read", "/tmp")
        self.assertEqual(
            v.hits, {"memory": "deny", "personal-mail": "sanitize", "tool-repo": "deny"}
        )
        self.assertEqual(v.action, "deny")
        self.assertFalse(v.blocked)
        (row,) = self.rows()
        self.assertEqual((row["source"], row["blocked"], row["enforced"]), ("rush/auto", False, []))

    def test_unreleased_paths_denied_to_tools_once_enforced(self):
        v = gate.check("roll/chores", "s", "u", "Read,Grep,Glob", str(config.REPO))
        self.assertEqual((v.hits, v.disallowed), ({"unreleased": "sanitize"}, ()))
        with mock.patch.object(gate, "ENFORCED", {"client-repo", "unreleased"}):
            v = gate.check("roll/chores", "s", "u", "Read,Grep,Glob", str(config.REPO))
        self.assertEqual(v.disallowed, ("Read(./docs/plans/**)", "Read(./STATUS.md)"))
        self.assertFalse(v.blocked)

    def test_clean_call_allowed(self):
        self.assertEqual(gate.check("evals/mail-keep", "s", "synthetic").action, "allow")

    def test_unknown_source_refused(self):
        with self.assertRaises(ValueError):
            gate.check("guts-man/whatever", "s", "u")
        with self.assertRaises(ValueError):
            brain.ClaudeCLI("sonnet", source="guts-man/whatever")

    def test_claude_brain_needs_a_source(self):
        with self.assertRaises(ValueError):
            brain.brain_for("claude:sonnet")
        self.assertIsInstance(brain.brain_for("ollama:llama3.1:8b"), brain.Brain)

    def test_disallowed_reaches_the_cli(self):
        done = mock.Mock(returncode=0, stdout=json.dumps({"result": "ok", "usage": {}}))
        b = brain.ClaudeCLI("sonnet", source="roll/chores", tools="Read", cwd=str(config.REPO))
        with (
            mock.patch.object(gate, "ENFORCED", {"client-repo", "unreleased"}),
            mock.patch("subprocess.run", return_value=done) as run,
        ):
            b.think("s", "u")
        self.assertIn(
            "--disallowedTools=Read(./docs/plans/**),Read(./STATUS.md)", run.call_args.args[0]
        )


class NoBypassTest(unittest.TestCase):
    """Nothing reaches Claude around the gate."""

    def test_claude_subprocess_only_in_brain_or_behind_gate_check(self):
        for path, tree in modules():
            if path.name == "brain.py":
                continue
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.FunctionDef):
                    continue
                if any(runs_claude(c) for c in calls(fn, "run")) or any(
                    runs_claude(c) for c in calls(fn, "Popen")
                ):
                    gated = any(
                        isinstance(c.func, ast.Attribute)
                        and isinstance(c.func.value, ast.Name)
                        and c.func.value.id == "gate"
                        for c in calls(fn, "check")
                    )
                    self.assertTrue(gated, f"{path.name}:{fn.name} runs claude without the gate")

    def test_every_claude_brain_names_a_known_source(self):
        for path, tree in modules():
            for name in ("ClaudeCLI", "brain_for"):
                for c in calls(tree, name):
                    if path.name == "brain.py" and name == "ClaudeCLI":
                        continue  # brain_for passes its own source through
                    where = f"{path.name}:{c.lineno}"
                    source = next((k.value for k in c.keywords if k.arg == "source"), None)
                    self.assertIsNotNone(source, f"{where}: {name} without source=")
                    if isinstance(source, ast.Constant):
                        gate.carries(source.value)


if __name__ == "__main__":
    unittest.main()
