import json
import subprocess
import sys
import unittest
from pathlib import Path

from light_labs import config

PATHS = config.REPO / ".github" / "eval-paths.txt"
# Everything run_one can load: its stages import the rest lazily.
STAGES = (
    "light_labs.evals.run_one",
    "light_labs.agents.rush.heartbeat",
    "light_labs.agents.rush.mail",
    "light_labs.evals.dbt_model",
    "light_labs.evals.commit_message",
)


def prefixes():
    lines = PATHS.read_text().splitlines()
    return [p for p in lines if p and not p.startswith("#")]


class EvalPathsTest(unittest.TestCase):
    """CI skips the Eval harness job unless a PR touches .github/eval-paths.txt."""

    def test_every_module_an_eval_stage_imports_is_listed(self):
        script = (
            f"import importlib, json, sys\nfor m in {STAGES!r}: importlib.import_module(m)\n"
            "print(json.dumps([m.__file__ for n, m in sys.modules.items()"
            " if n.startswith('light_labs') and getattr(m, '__file__', None)]))"
        )
        done = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, check=True
        )
        files = [str(Path(f).resolve().relative_to(config.REPO)) for f in json.loads(done.stdout)]
        listed = prefixes()
        missing = [f for f in files if not any(f.startswith(p) for p in listed)]
        self.assertEqual(missing, [], f"add these to {PATHS.name}")

    def test_listed_paths_exist(self):
        for p in prefixes():
            self.assertTrue((config.REPO / p).exists(), p)
