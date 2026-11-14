import json
import tempfile
import unittest
from pathlib import Path

from light_labs import gitops
from light_labs.agents.roll import chores, holds
from light_labs.core.store import Store

GREEN = [{"status": "COMPLETED", "conclusion": "SUCCESS"}]
RED = [{"status": "COMPLETED", "conclusion": "FAILURE"}]


class FakeRepo:
    """The checkout and, through `at`, the fixer's worktree of it. `edits` is what `git
    status` reports there, one list per Claude turn; `ci` the bucket each push ends in."""

    def __init__(self, checks=RED, edits=(), ci=()):
        self.path = Path("/src/de")
        self.checks, self.edits, self.ci = checks, list(edits), list(ci)
        self.calls, self.pushed, self.state = [], 0, "OPEN"

    def at(self, path):
        return self

    def gh_json(self, *args):
        if args[:2] == ("pr", "view"):
            return {
                "number": 7, "title": "Bump b from 1.0.0 to 1.1.0 in /t", "state": self.state,
                "headRefName": "dependabot/b", "headRefOid": f"sha{self.pushed}",
                "files": [{"path": "t/uv.lock"}], "statusCheckRollup": self.checks,
                "mergeable": "MERGEABLE", "body": "Bumps b.", "url": "https://x/7",
            }  # fmt: skip
        if args[:2] == ("pr", "checks"):
            bucket = self.ci.pop(0) if self.pushed and self.ci else "fail"
            return [{"name": "test", "bucket": bucket, "link": ""}]
        raise AssertionError(args)

    def gh(self, *args, check=True):
        self.calls.append(("gh", *args))
        return ""

    def git(self, *args, check=True):
        self.calls.append(("git", *args))
        if args[0] == "status":
            return "\n".join(f" M {p}" for p in (self.edits.pop(0) if self.edits else []))
        if args[0] == "push":
            self.pushed += 1
        if args[0] == "rev-parse":
            return f"sha{self.pushed}"
        return ""


class Claude:
    """Answers in order; records the models asked and the prompts they got."""

    def __init__(self, *raws):
        self.raws, self.models, self.prompts = list(raws), [], []

    def __call__(self, model, cwd):
        self.models.append(model)
        return self

    def think(self, system, user, **kw):
        self.prompts.append(user)
        raw = self.raws.pop(0)
        if isinstance(raw, Exception):
            raise raw
        return raw


class HoldsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store, self.sent = Store(Path(self.tmp.name)), []

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, text, buttons):
        self.sent.append((text, [label for label, _ in buttons]))
        return len(self.sent)

    def hold(self, why="CI fail", checks="fail", model=None):
        return self.store.enqueue(
            chores.KIND, {"repo": "pj/de", "pr": 7, "head": "sha0"}, f"HOLD: {why}",
            "Bump b from 1.0.0 to 1.1.0 in /t", escalate=why,
            facts={"tier": "minor", "checks": checks},
            big_brother={"model": model, "verdict": "HOLD", "why": why, "critique": ""},
        )  # fmt: skip

    def holds(self, repo, *raws, spec="/src/de:admin"):
        self.claude = Claude(*raws)
        return holds.Holds(self.store, self.send, spec, brain=self.claude, repo=repo.at,
                           sleep=lambda s: None)  # fmt: skip

    def test_each_hold_is_texted_once_and_merge_is_offered_only_on_green(self):
        self.hold()
        h = self.holds(FakeRepo())
        self.assertEqual((h.present_new(), h.present_new()), (1, 0))
        text, buttons = self.sent[0]
        self.assertIn("pj/de#7", text)
        self.assertEqual(buttons, ["Fix it", "Leave"])
        h.present(self.hold("does /t use the old default?", checks="pass"))
        self.assertEqual(self.sent[-1][1], ["Fix it", "Merge", "Leave"])

    def test_a_fix_is_pushed_then_ci_decides_and_the_hold_follows_the_new_head(self):
        item = self.hold()
        repo = FakeRepo(edits=[["t/app.py"]], ci=["pass"])
        self.holds(repo, "FIXED: renamed the import b dropped in 1.1").turn(item["id"])
        self.assertEqual(self.claude.models, ["sonnet"])
        self.assertIn(("git", "push", "-q", "origin", "HEAD:dependabot/b"), repo.calls)
        self.assertIn("CI is green", self.sent[-1][0])
        self.assertEqual(self.sent[-1][1], ["Fix it", "Merge", "Leave"])
        now = self.store.get(item["id"])
        self.assertEqual(now["target"]["head"], "sha1")
        (turn,) = now["dialogue"]
        self.assertEqual((turn["model"], turn["commit"], turn["files"], turn["auto"]),
                         ("sonnet", "sha1", ["t/app.py"], True))  # fmt: skip
        self.assertTrue(any(c[:3] == ("git", "worktree", "remove") for c in repo.calls))

    def test_red_ci_climbs_the_ladder_and_a_spent_ladder_offers_the_top_model_and_heeler(self):
        item = self.hold()
        repo = FakeRepo(edits=[["t/app.py"], []], ci=["fail"])
        self.holds(repo, "FIXED: pinned c", "STUCK: b 1.1 needs python 3.13").turn(item["id"])
        self.assertEqual(self.claude.models, ["sonnet", "opus"])
        text, buttons = self.sent[-1]
        self.assertEqual(buttons, [f"Try {holds.TOP}", "Leave"])
        self.assertIn("open Heeler", text)
        self.assertIn("pinned c", self.claude.prompts[1])  # opus sees what sonnet tried

    def test_pjs_reply_is_a_turn_and_its_red_ci_waits_for_him(self):
        item = self.hold("does /t use the old default?", checks="pass", model="sonnet")
        repo = FakeRepo(checks=GREEN)
        h = self.holds(repo, "ANSWER: safe to merge; /t sets the option itself\nask: merge it?")
        h.turn(item["id"], note="check transformation/t for the default")
        self.assertIn("pj: check transformation/t", self.claude.prompts[0])
        self.assertIn("Question: merge it?", self.sent[-1][0])
        self.assertEqual(self.sent[-1][1], ["Fix it", "Merge", "Leave"])
        who = [d["who"] for d in self.store.get(item["id"])["dialogue"]]
        self.assertEqual(who, ["pj", "claude:sonnet"])
        self.assertFalse(repo.pushed)

    def test_a_fix_that_touches_ci_config_is_not_pushed(self):
        item = self.hold()
        repo = FakeRepo(edits=[[".github/workflows/ci.yml"], []])
        self.holds(repo, "FIXED: skipped the job", "STUCK: no").turn(item["id"])
        self.assertFalse(repo.pushed)
        self.assertEqual(self.store.get(item["id"])["dialogue"][0]["kind"], "STUCK")

    def test_caps(self):
        item = self.hold()
        h = self.holds(FakeRepo(), *["STUCK: no"] * 9)
        h.turn(item["id"])
        self.assertEqual(self.claude.models, ["sonnet", "opus"])  # STUCK climbs unasked
        self.store.update(item["id"], dialogue=[{"at": "2026-01-01", "auto": True}] * 3)
        h.turn(item["id"])
        self.assertEqual(len(self.claude.models), 2)  # three attempts: Claude isn't asked
        self.assertIn("3 attempts", self.sent[-1][0])
        self.store.update(item["id"], dialogue=[{"at": holds.now(), "model": "opus"}] * 5)
        h.turn(item["id"], top=True)
        self.assertEqual(len(self.claude.models), 2)
        self.assertIn("my cap", self.sent[-1][0])

    def test_merge_is_pjs_tap_at_the_head_he_saw_and_the_record_says_who_decided(self):
        asked = self.hold("does /t use the old default?", checks="pass", model="sonnet")
        repo = FakeRepo(checks=GREEN)
        h = self.holds(repo)
        self.assertEqual(h.merge(asked["id"]), "Merged pj/de#7.")
        merge = next(c for c in repo.calls if c[:3] == ("gh", "pr", "merge"))
        self.assertEqual(merge[merge.index("--match-head-commit") + 1], "sha0")
        self.assertIn("--admin", merge)
        (done,) = [json.loads(p.read_text()) for p in self.store.root.glob("queue/sent/*.json")]
        self.assertEqual(chores.outcome(done), ("merge", "pj"))  # PJ overruled the hold
        fixed = self.hold("needs a code change", model="opus")
        self.store.update(fixed["id"], dialogue=[{"at": "x", "model": "sonnet", "commit": "sha1"}])
        self.holds(repo, spec="/src/de").merge(fixed["id"])
        merge = [c for c in repo.calls if c[:3] == ("gh", "pr", "merge")][-1]
        self.assertNotIn("--admin", merge)
        done = json.loads((self.store.root / f"queue/sent/{fixed['id']}.json").read_text())
        self.assertEqual(chores.outcome(done), ("hold", "claude"))  # it did need work

    def test_leave_stops_the_texts(self):
        item = self.hold()
        h = self.holds(FakeRepo())
        h.leave(item["id"])
        self.assertEqual(h.present_new(), 0)

    def test_parse(self):
        self.assertEqual(holds.parse("**FIXED:** x\nask: ok?"), ("FIXED", "x", "ok?"))
        self.assertEqual(holds.parse("who knows")[0], "STUCK")


class WaitTest(unittest.TestCase):
    def test_ci_is_green_only_when_every_check_passes(self):
        repo = FakeRepo(ci=["pass"])
        repo.pushed = 1
        h = holds.Holds(None, None, "", repo=repo.at, sleep=lambda s: None)
        self.assertTrue(h._ci(repo, 7))
        self.assertFalse(h._ci(repo, 7))
        self.assertTrue(callable(gitops.wait_for_checks))


if __name__ == "__main__":
    unittest.main()
