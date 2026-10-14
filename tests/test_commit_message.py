import importlib.util
import unittest
from pathlib import Path

from light_labs.evals import commit_message as cm

INPUT = {
    "repo": "light-labs",
    "files": [
        {"path": "light_labs/gitops.py", "additions": 40, "deletions": 3},
        {"path": "tests/test_gitops.py", "additions": 20, "deletions": 0},
    ],
    "diff": "diff --git a/light_labs/gitops.py b/light_labs/gitops.py\n+    # see #12\n",
    "reference": "fix: x\n\ny",
    "accept_types": ["fix"],
}
GOOD = "fix: keep locked worktrees in tidy\n\ngitops.py lists them for review."


class FlagsTest(unittest.TestCase):
    def failing(self, message, **inp):
        result, notes = cm.flags(message, {**INPUT, **inp})
        return sorted(k for k, v in result.items() if not v), notes

    def test_a_good_message_passes(self):
        self.assertEqual(self.failing(GOOD), ([], ""))

    def test_each_rule(self):
        cases = {
            "fix: keep locked worktrees.\n\nbody": "subject_format",
            "Fixed tidy\n\nbody": "subject_format",
            "fix: " + "x" * 70 + "\n\nbody": "subject_length",
            "feat: keep locked worktrees\n\nbody": "type_fits",
            "fix: keep locked worktrees": "has_body",
            "fix: keep locked worktrees\nno blank line": "has_body",
            "fix: keep locked worktrees\n\nsee cli.py": "no_unknown_files",
            "fix: keep locked worktrees\n\nfollows #13": "no_invented_refs",
            "fix: keep locked worktrees\n\nsee https://x.dev": "no_invented_refs",
            "fix: x\n\ny\n\nCo-Authored-By: a <b@c>": "no_trailers",
        }
        for message, flag in cases.items():
            failed, notes = self.failing(message)
            self.assertIn(flag, failed, message)
            self.assertIn(flag, notes)

    def test_what_the_diff_shows_is_fair_game(self):
        message = "fix(gitops): keep worktrees\n\ntest_gitops.py covers it; see #12."
        self.assertEqual(self.failing(message)[0], [])

    def test_clean_strips_a_fence_around_everything(self):
        self.assertEqual(cm.clean("```\n" + GOOD + "\n```"), GOOD)
        self.assertEqual(cm.clean(GOOD), GOOD)


class BuildTest(unittest.TestCase):
    def test_reference_is_cleaned(self):
        squash = (
            "ci: gate it (#5) (#174)\n\n## Summary\nWhy.\n\n"
            "https://claude.ai/code/session_x\n\n## Test plan\n- just check\n\n"
            "Co-Authored-By: a <b@c>"
        )
        self.assertEqual(cm.reference(squash), "ci: gate it\n\nWhy.")

    def test_excerpt_omits_lock_files_and_caps_each_file(self):
        big = "diff --git a/a.py b/a.py\n" + "\n".join(f"+{i}" for i in range(100))
        lock = "diff --git a/uv.lock b/uv.lock\n+x\n"
        out = cm.excerpt(big + "\n" + lock)
        self.assertIn("more lines]", out)
        self.assertIn("uv.lock (lock file; diff omitted)", out)
        self.assertLess(len(out), cm.DIFF_BUDGET)

    def test_mentions_skip_tests_locks_and_generic_names(self):
        paths = ["light_labs/gitops.py", "tests/test_gitops.py", "uv.lock", "README.md"]
        self.assertEqual(cm.mentions(paths), ["gitops", "light_labs"])
        self.assertIn("ci", cm.mentions([".github/workflows/ci.yml"]))

    def test_accept_types(self):
        self.assertEqual(cm.accept_types("refactor", ["a.py"]), ["chore", "refactor"])
        self.assertIn("docs", cm.accept_types("feat", ["README.md", "docs/a.md"]))


@unittest.skipUnless(importlib.util.find_spec("yaml"), "needs the analytics dependency group")
class StageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import yaml

        cls.stage = yaml.safe_load(Path("evals/stages/commit-message.yaml").read_text())

    def test_at_least_thirty_fixtures_with_unique_ids(self):
        ids = [f["id"] for f in self.stage["fixtures"]]
        self.assertGreaterEqual(len(ids), 30)
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_reference_passes_the_flags(self):
        for f in self.stage["fixtures"]:
            result, notes = cm.flags(f["input"]["reference"], f["input"])
            self.assertTrue(all(result.values()), f"{f['id']}: {notes}")

    def test_the_largest_prompt_fits_rolls_context(self):
        from light_labs.agents import roll

        longest = max(
            len(roll.system_prompt()) + len(cm.prompt(f["input"])) for f in self.stage["fixtures"]
        )
        # ~3.5 characters per token; leave 1k tokens for the answer.
        self.assertLess(longest / 3.5, roll.NUM_CTX - 1024)

    def test_require_names_every_flag(self):
        result, _ = cm.flags(GOOD, INPUT)
        self.assertEqual(set(self.stage["defaults"]["require"]), set(result))


if __name__ == "__main__":
    unittest.main()
