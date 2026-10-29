import json
import tempfile
import unittest
from pathlib import Path

from light_labs.agents.roll import chores
from light_labs.core.store import Store

GREEN = [{"status": "COMPLETED", "conclusion": "SUCCESS"}]
RED = [{"status": "COMPLETED", "conclusion": "FAILURE"}]


def pr(number, title, files=("orchestration/airflow/uv.lock",), checks=GREEN, head=None):
    return {
        "number": number,
        "title": title,
        "headRefName": f"dependabot/{number}",
        "headRefOid": head or f"sha{number}",
        "files": [{"path": f} for f in files],
        "statusCheckRollup": checks,
        "mergeable": "MERGEABLE",
        "body": "Bumps x.\n\nDependabot will resolve any conflicts with this PR",
    }


class FakeRepo:
    path = Path("/repo")

    def __init__(self, prs, states=None):
        self.prs, self.states, self.calls = prs, states or {}, []

    def gh_json(self, *args):
        if args[:2] == ("repo", "view"):
            return {"nameWithOwner": "pj/de"}
        if args[:2] == ("pr", "list"):
            return self.prs
        if args[:2] == ("pr", "view"):
            return self.states[int(args[2])]
        raise AssertionError(args)

    def gh(self, *args, check=True):
        self.calls.append(args)
        return ""


class Brother:
    def __init__(self, raw):
        self.raw, self.models = raw, []

    def __call__(self, model):
        self.models.append(model)
        return self

    def think(self, system, user, **kw):
        return self.raw


class Roll:
    """A brain with probabilities: yes at `p`."""

    def __init__(self, p):
        self.p = p

    def choose(self, system, user, choices, num_ctx=None):
        return {"yes": self.p, "no": 1 - self.p}


MERGE = "MERGE\nwhy: patch release, lock file only\nroll: right"


class ChoresTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def chores(self, repo, raw=MERGE, apply=True, roll=None, cap=10, admin=False):
        self.brother = Brother(raw)
        return chores.Chores(repo, self.store, roll or Roll(0.9), self.brother, apply, cap, admin)

    def test_title_and_jump(self):
        self.assertEqual(
            chores.parse_title("chore(deps-dev): Bump ruff from 0.16.10 to 0.17.1 in /x/y"),
            ("ruff", "0.16.10", "0.17.1", "/x/y"),
        )
        self.assertEqual(
            chores.parse_title("Update airbytehq/airbyte requirement from ~> 0.6 to ~> 1.3 in /t")[1:3],
            ("~> 0.6", "~> 1.3"),
        )  # fmt: skip
        self.assertEqual(chores.jump("1.12.1", "1.12.3"), "patch")
        self.assertEqual(chores.jump("6.18.0", "6.19.0"), "minor")
        self.assertEqual(chores.jump("0.16.10", "0.17.1"), "major")  # below 1.0
        self.assertEqual(chores.jump("2.11.0", "3.3.2"), "major")
        self.assertEqual(chores.jump("7", "8"), "major")

    def test_tier_rises_when_more_than_lock_files_change(self):
        f = chores.facts(
            pr(1, "Bump a from 1.0.0 to 1.0.1", files=("x/pyproject.toml", "x/uv.lock"))
        )
        self.assertEqual((f["jump"], f["tier"]), ("patch", "major"))
        self.assertNotIn("Dependabot will resolve", f["body"])
        risky = pr(2, "Bump a from 1.0.0 to 1.0.1", files=("x/uv.lock",))
        risky["body"] = "Breaking: dbt-core moved to an extra."
        self.assertEqual(chores.facts(risky)["tier"], "minor")

    def test_merge_is_pinned_to_the_reviewed_head_and_recorded(self):
        repo = FakeRepo([pr(7, "Bump dbt-core from 1.12.5 to 1.12.6 in /t")])
        self.assertEqual(self.chores(repo).run()[0][1], "merged")
        self.assertEqual(self.brother.models, ["haiku"])
        merge = next(c for c in repo.calls if c[:2] == ("pr", "merge"))
        self.assertIn("--match-head-commit", merge)
        self.assertEqual(merge[merge.index("--match-head-commit") + 1], "sha7")
        (item,) = [json.loads(p.read_text()) for p in self.store.root.glob("queue/sent/*.json")]
        self.assertEqual(item["roll"], {"choice": "yes", "p_yes": 0.9})
        self.assertEqual(item["big_brother"]["model"], "haiku")
        self.assertEqual(item["reason"], "merged by roll")
        self.assertNotIn("--admin", merge)

    def test_admin_is_opt_in(self):
        repo = FakeRepo([pr(7, "Bump dbt-core from 1.12.5 to 1.12.6 in /t")])
        self.chores(repo, admin=True).run()
        merge = next(c for c in repo.calls if c[:2] == ("pr", "merge"))
        self.assertIn("--admin", merge)

    def test_dry_run_touches_nothing(self):
        repo = FakeRepo([pr(7, "Bump dbt-core from 1.12.5 to 1.12.6 in /t")])
        self.assertEqual(self.chores(repo, apply=False).run()[0][1], "would merge")
        self.assertEqual(repo.calls, [])
        self.assertEqual(self.store.pending(), [])

    def test_red_ci_is_held_by_code_without_big_brother(self):
        repo = FakeRepo([pr(158, "Bump apache-airflow from 2.11.0 to 3.3.2 in /a", checks=RED)])
        action = self.chores(repo).run()[0][1]
        self.assertEqual(action, "hold")
        self.assertEqual(self.brother.models, [])
        self.assertEqual(self.store.pending()[0]["escalate"], "CI fail")

    def test_hold_waits_for_pj_and_his_merge_is_the_outcome(self):
        repo = FakeRepo([pr(9, "Bump b from 1.0 to 1.1 in /t")])
        raw = "HOLD: does /t rely on b's old default?\nwhy: default changed\nroll: wrong, notes say so"
        self.chores(repo, raw=raw).run()
        (item,) = self.store.pending()
        self.assertEqual(item["big_brother"]["critique"], "wrong, notes say so")
        self.assertEqual(self.brother.models, ["sonnet"])
        self.assertEqual(self.chores(repo, raw=raw).run()[0][1], "pending")  # no second call
        repo.states[9] = {"state": "MERGED", "headRefOid": "sha9", "mergedBy": {"login": "pj"}}
        repo.prs = []
        self.chores(repo).run()
        self.assertEqual(chores.scorecard(self.store)["minor"], {
            "n": 1, "agree": 0, "false_yes": 1, "overruled": 1})  # fmt: skip

    def test_one_merge_per_directory_and_the_daily_cap(self):
        repo = FakeRepo([
            pr(1, "Bump a from 1.0.0 to 1.0.1 in /t"),
            pr(2, "Bump b from 1.0.0 to 1.0.1 in /t"),
            pr(3, "Bump c from 1.0.0 to 1.0.1 in /u"),
        ])  # fmt: skip
        actions = [a for _, a, _ in self.chores(repo, cap=1).run()]
        self.assertEqual(actions, ["merged", "later", "hold"])

    def test_fixtures_label_by_pj_over_claude_one_per_pr(self):
        held = "HOLD: ok?\nwhy: unsure\nroll: wrong"
        repo = FakeRepo([pr(9, "Bump b from 1.0 to 1.1 in /t"), pr(10, "Bump c from 2.0 to 2.0.1")])
        self.chores(repo, raw=held).run()
        repo.prs = [pr(10, "Bump c from 2.0 to 2.0.1", head="new10")]  # rebased: decided again
        repo.states[9] = {"state": "MERGED", "mergedBy": {"login": "pj"}}
        self.chores(repo, raw=MERGE).run()
        bodies = {9: "notes 9", 10: "notes 10\nDependabot will resolve any conflicts"}
        made = chores.fixtures(self.store, lambda repo, n: bodies[n])
        self.assertEqual(
            [(f["id"], f["expect"]["label"], f["source"]) for f in made],
            [("de_9", "merge", "pj"), ("de_10", "merge", "claude")],
        )
        self.assertEqual(made[1]["input"]["body"], "notes 10")
        self.assertEqual(made[1]["input"]["head"], "new10")
        self.assertEqual(chores.fixtures(self.store, bodies.get, known={"de_9", "de_10"}), [])

    def test_code_holds_make_no_fixture(self):
        self.chores(FakeRepo([pr(9, "Bump b from 1.0 to 1.1", checks=RED)])).run()
        self.assertEqual(chores.fixtures(self.store, lambda *a: ""), [])

    def test_behaviour_changes_go_one_tier_up(self):
        def tier(notes):
            p = pr(1, "Bump dbt-core from 1.12.5 to 1.12.6")
            p["body"] = notes
            return chores.facts(p)["tier"]

        self.assertEqual(tier("Wildcard selectors now match nested models"), "minor")
        self.assertEqual(tier("Rename internals; no user-facing behavior change"), "patch")

    def test_verdict_without_a_line_is_a_hold(self):
        self.assertEqual(chores.verdict("looks fine to me")[0], "HOLD")
        self.assertEqual(chores.verdict("**MERGE**\nwhy: ok\nroll: right")[:3], ("MERGE", "", "ok"))


if __name__ == "__main__":
    unittest.main()


class SlimInstallTest(unittest.TestCase):
    def test_roll_brain_needs_no_dagster(self):
        # `lab` is installed without the orchestration group; dagster must stay optional.
        import subprocess
        import sys

        code = (
            "import sys; sys.modules['dagster'] = None\n"
            "from light_labs.agents.roll import chores\n"
            "chores.roll_brain(None)\n"
        )
        subprocess.run([sys.executable, "-c", code], check=True)
