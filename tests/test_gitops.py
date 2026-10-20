import io
import json
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from light_labs import gitops

NOW = datetime(2026, 10, 13, tzinfo=UTC)


def sh(cwd, *cmd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class FakeGh(gitops.Repo):
    """A real git repo; `gh` answers come from `responses` keyed by the first two args."""

    def __init__(self, path, responses=None):
        super().__init__(path)
        self.responses = responses or {}
        self.calls = []

    def gh(self, *args, check=True):
        self.calls.append(args)
        answer = self.responses.get(args[:2], "")
        return answer(args) if callable(answer) else answer


class RepoCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.remote = root / "remote.git"
        sh(root, "git", "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.path = root / "work"
        sh(root, "git", "clone", "-q", str(self.remote), str(self.path))
        for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
            sh(self.path, "git", "config", key, value)
        self.commit("init")
        sh(self.path, "git", "push", "-q", "-u", "origin", "main")
        sh(self.path, "git", "remote", "set-head", "origin", "main")
        self.repo = FakeGh(self.path)

    def commit(self, name):
        (self.path / name).write_text(name)
        sh(self.path, "git", "add", name)
        sh(self.path, "git", "commit", "-q", "-m", name)
        return sh(self.path, "git", "rev-parse", "HEAD")

    def branch(self, name, push=False, merge=False):
        """A branch with one commit; `merge` squash-merges it into main like GitHub does."""
        sh(self.path, "git", "checkout", "-q", "-b", name, "main")
        sha = self.commit(name.replace("/", "_"))
        if push:
            sh(self.path, "git", "push", "-q", "origin", name)
        sh(self.path, "git", "checkout", "-q", "main")
        if merge:
            sh(self.path, "git", "merge", "-q", "--squash", name)
            sh(self.path, "git", "commit", "-q", "-m", f"squash {name}")
            sh(self.path, "git", "push", "-q", "origin", "main")
        return sha


class TidyTest(RepoCase):
    def plan(self, prs):
        return {
            (a.kind, a.target): (a.delete, a.reason)
            for a in gitops.plan_tidy(self.repo, prs, now=NOW)
        }

    def test_merged_branches_go_unmerged_work_stays(self):
        merged = self.branch("feature/done", push=True, merge=True)
        self.branch("feature/wip")
        sh(self.path, "git", "branch", "already-in", "main")
        prs = [
            {"number": 1, "headRefName": "feature/done", "headRefOid": merged, "state": "MERGED"}
        ]
        got = self.plan(prs)
        self.assertEqual(got[("local", "feature/done")], (True, "PR #1 merged"))
        self.assertEqual(got[("remote", "feature/done")], (True, "PR #1 merged"))
        self.assertFalse(got[("local", "feature/wip")][0])
        self.assertIn("1 commit(s) not on main", got[("local", "feature/wip")][1])
        self.assertEqual(got[("local", "already-in")], (True, "no PR, already in main"))
        self.assertNotIn(("local", "main"), got)

    def test_branch_that_moved_after_its_merge_is_kept(self):
        merged = self.branch("feature/more", merge=True)
        sh(self.path, "git", "checkout", "-q", "feature/more")
        self.commit("after-merge")
        sh(self.path, "git", "checkout", "-q", "main")
        prs = [
            {"number": 2, "headRefName": "feature/more", "headRefOid": merged, "state": "MERGED"}
        ]
        delete, reason = self.plan(prs)[("local", "feature/more")]
        self.assertFalse(delete)
        self.assertIn("moved after", reason)

    def test_closed_unmerged_waits_for_stale_days_open_is_untouched(self):
        self.branch("old", push=True)
        self.branch("recent")
        self.branch("open")
        prs = [
            {"number": 3, "headRefName": "old", "state": "CLOSED",
             "closedAt": (NOW - timedelta(days=40)).isoformat()},
            {"number": 4, "headRefName": "recent", "state": "CLOSED",
             "closedAt": (NOW - timedelta(days=2)).isoformat()},
            {"number": 5, "headRefName": "open", "state": "OPEN"},
        ]  # fmt: skip
        got = self.plan(prs)
        self.assertEqual(got[("local", "old")][0], True)
        self.assertEqual(got[("remote", "old")][0], True)
        self.assertFalse(got[("local", "recent")][0])
        self.assertFalse(any(target == "open" for _, target in got))

    def test_worktree_with_uncommitted_changes_is_kept(self):
        merged = self.branch("feature/wt", merge=True)
        wt = self.path.parent / "wt"
        sh(self.path, "git", "worktree", "add", "-q", str(wt), "feature/wt")
        (wt / "scratch").write_text("unsaved")
        prs = [{"number": 6, "headRefName": "feature/wt", "headRefOid": merged, "state": "MERGED"}]
        got = self.plan(prs)
        worktree = next(v for (kind, _), v in got.items() if kind == "worktree")
        self.assertEqual(worktree, (False, "feature/wt: uncommitted changes"))
        self.assertNotIn(("local", "feature/wt"), got)

    def test_locked_worktree_is_kept(self):
        merged = self.branch("feature/lk", merge=True)
        wt = self.path.parent / "lk"
        sh(self.path, "git", "worktree", "add", "-q", str(wt), "feature/lk")
        sh(self.path, "git", "worktree", "lock", "--reason", "agent pid 1", str(wt))
        prs = [{"number": 7, "headRefName": "feature/lk", "headRefOid": merged, "state": "MERGED"}]
        got = self.plan(prs)
        worktree = next(v for (kind, _), v in got.items() if kind == "worktree")
        self.assertFalse(worktree[0])
        self.assertIn("locked (agent pid 1)", worktree[1])
        self.assertNotIn(("local", "feature/lk"), got)

    def test_one_failed_deletion_does_not_stop_the_rest(self):
        merged = self.branch("feature/a", merge=True)
        actions = [
            gitops.Action("local", "no-such-branch", "x", True),
            gitops.Action("local", "feature/a", "PR merged", True),
        ]
        out = io.StringIO()
        failed = gitops.apply_tidy(self.repo, actions, out=out)
        self.assertEqual([a.target for a in failed], ["no-such-branch"])
        self.assertIn("deleted local feature/a", out.getvalue())
        self.assertTrue(merged)

    def test_apply_deletes_only_the_delete_rows(self):
        merged = self.branch("feature/done", push=True, merge=True)
        self.branch("feature/wip")
        prs = [
            {"number": 1, "headRefName": "feature/done", "headRefOid": merged, "state": "MERGED"}
        ]
        gitops.apply_tidy(self.repo, gitops.plan_tidy(self.repo, prs, now=NOW), out=io.StringIO())
        local = sh(self.path, "git", "branch", "--format=%(refname:short)").split()
        self.assertEqual(sorted(local), ["feature/wip", "main"])
        self.assertNotIn("feature/done", sh(self.path, "git", "ls-remote", "--heads", "origin"))


class ShipTest(RepoCase):
    def test_refuses_on_main_and_without_a_message(self):
        with self.assertRaisesRegex(gitops.GitError, "branch first"):
            gitops.ship(self.repo, "msg", check=["true"], out=io.StringIO())
        sh(self.path, "git", "checkout", "-q", "-b", "feature/x")
        (self.path / "new").write_text("x")
        with self.assertRaisesRegex(gitops.GitError, "no commit message"):
            gitops.ship(self.repo, check=["true"], out=io.StringIO())

    def test_failed_check_commits_nothing(self):
        sh(self.path, "git", "checkout", "-q", "-b", "feature/x")
        (self.path / "new").write_text("x")
        out = io.StringIO()
        with self.assertRaisesRegex(gitops.GitError, "nothing committed"):
            gitops.ship(self.repo, "feat: x", check=["sh", "-c", "echo boom; exit 1"], out=out)
        self.assertIn("boom", out.getvalue())
        self.assertEqual(sh(self.path, "git", "log", "-1", "--format=%s"), "init")

    def test_check_commit_push_and_pr(self):
        sh(self.path, "git", "checkout", "-q", "-b", "feature/x")
        (self.path / "new").write_text("x")
        self.repo.responses[("pr", "list")] = "[]"
        self.repo.responses[("pr", "create")] = "https://github.com/o/r/pull/7"
        url = gitops.ship(self.repo, "feat: x\n\nWhy.", check=["true"], out=io.StringIO())
        self.assertEqual(url, "https://github.com/o/r/pull/7")
        self.assertIn("feature/x", sh(self.path, "git", "ls-remote", "--heads", "origin"))
        create = next(c for c in self.repo.calls if c[:2] == ("pr", "create"))
        self.assertEqual(create[create.index("--title") + 1], "feat: x")
        self.assertIn("Why.", create[create.index("--body") + 1])


class LandTest(RepoCase):
    def test_red_ci_is_not_merged_and_says_why(self):
        self.repo.responses[("pr", "view")] = '{"state": "OPEN", "headRefName": "f", "files": []}'
        self.repo.responses[("pr", "checks")] = (
            '[{"name": "Tests", "bucket": "fail", '
            '"link": "https://github.com/o/r/actions/runs/42/job/1"},'
            '{"name": "Hooks", "bucket": "pass", "link": ""}]'
        )
        self.repo.responses[("run", "view")] = "Tests\tstep\tAssertionError: 1 != 2"
        out = io.StringIO()
        with self.assertRaisesRegex(gitops.GitError, "not merged"):
            gitops.land(self.repo, 9, out=out, sleep=lambda s: None)
        self.assertIn("failed: Tests", out.getvalue())
        self.assertIn("AssertionError: 1 != 2", out.getvalue())
        self.assertFalse(any(c[:2] == ("pr", "merge") for c in self.repo.calls))

    def land_from(self, path):
        """Land feature/x from `path` with GitHub faked: merge squashes it into origin's main,
        the API call deletes origin's branch."""
        repo = FakeGh(path)
        repo.responses = self.repo.responses
        self.repo.responses[("pr", "view")] = (
            '{"state": "OPEN", "headRefName": "feature/x", "files": []}'
        )

        def merge(args):
            clone = self.path.parent / "github"
            sh(self.path.parent, "git", "clone", "-q", str(self.remote), str(clone))
            sh(clone, "git", "merge", "-q", "--squash", "origin/feature/x")
            sh(clone, "git", "-c", "user.name=gh", "-c", "user.email=g@h", "commit", "-qm", "x")
            sh(clone, "git", "push", "-q", "origin", "main")

        self.repo.responses[("pr", "merge")] = merge
        self.repo.responses[("api", "-X")] = lambda args: sh(
            self.path, "git", "push", "-q", "origin", "--delete", "feature/x"
        )
        out = io.StringIO()
        gitops.land(repo, 9, wait=False, out=out)
        return repo, out.getvalue()

    def assert_gone(self):
        self.assertEqual(sh(self.path, "git", "branch", "--list", "feature/x"), "")
        self.assertNotIn("feature/x", sh(self.path, "git", "ls-remote", "--heads", "origin"))

    def test_lands_while_another_worktree_has_main(self):
        self.branch("feature/x", push=True)
        wt = self.path.parent / "wt"
        sh(self.path, "git", "worktree", "add", "-q", str(wt), "feature/x")
        repo, out = self.land_from(wt)
        self.assertEqual(repo.branch(), "")  # detached: main is the other worktree's
        self.assertEqual(sh(wt, "git", "log", "-1", "--format=%s"), "x")
        self.assertIn("detached (main is checked out in", out)
        self.assert_gone()

    def test_lands_onto_main_when_it_is_free(self):
        self.branch("feature/x", push=True)
        sh(self.path, "git", "checkout", "-q", "feature/x")
        repo, out = self.land_from(self.path)
        self.assertEqual(repo.branch(), "main")
        self.assertEqual(sh(self.path, "git", "log", "-1", "--format=%s"), "x")
        self.assertIn("on main; deleted feature/x", out)
        self.assert_gone()

    def test_a_branch_open_in_another_worktree_is_kept(self):
        self.branch("feature/x", push=True)
        wt = self.path.parent / "wt"
        sh(self.path, "git", "worktree", "add", "-q", str(wt), "feature/x")
        _, out = self.land_from(self.path)  # landed from main's checkout
        self.assertIn("kept feature/x (checked out in", out)
        self.assertEqual(sh(wt, "git", "branch", "--show-current"), "feature/x")


class StatusTest(RepoCase):
    def test_checkout_worktrees_and_open_prs_in_one_look(self):
        self.branch("feature/done", push=True, merge=True)
        wt = self.path.parent / "wt"
        sh(self.path, "git", "worktree", "add", "-q", str(wt), "feature/done")
        (self.path / "new.txt").write_text("x")
        self.repo.responses[("pr", "list")] = json.dumps([
            {"number": 5, "title": "done", "headRefName": "feature/done", "state": "MERGED",
             "statusCheckRollup": [], "isDraft": False},
            {"number": 6, "title": "wip", "headRefName": "feature/wip", "state": "OPEN",
             "statusCheckRollup": [{"name": "Tests", "status": "COMPLETED", "conclusion": "FAILURE"}],
             "isDraft": False},
        ])  # fmt: skip
        out = io.StringIO()
        gitops.status(self.repo, out=out)
        text = out.getvalue()
        self.assertIn("on main: 1 changed, 0 ahead / 0 behind origin/main", text)
        self.assertIn("?? new.txt", text)
        self.assertIn("[feature/done] 0 changed", text)
        self.assertIn("#5 merged: done · `lab git tidy` removes it", text)
        self.assertIn("#6 open, checks fail: wip [feature/wip]", text)
        self.assertIn("failing: Tests", text)

    def test_one_pr_in_detail(self):
        self.repo.responses[("pr", "view")] = json.dumps({
            "number": 7, "title": "x", "state": "OPEN", "headRefName": "feature/x",
            "baseRefName": "main", "mergeable": "MERGEABLE", "mergeStateStatus": "BLOCKED",
            "reviewDecision": None, "isDraft": False, "url": "https://github.com/o/r/pull/7",
            "mergeCommit": None,
            "statusCheckRollup": [
                {"name": "Hooks", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"name": "Tests", "status": "COMPLETED", "conclusion": "FAILURE",
                 "detailsUrl": "https://github.com/o/r/actions/runs/1/job/2"},
                {"name": "Eval", "status": "IN_PROGRESS", "conclusion": None},
            ],
        })  # fmt: skip
        out = io.StringIO()
        gitops.status(self.repo, pr=7, fetch=False, out=out)
        text = out.getvalue()
        self.assertIn("#7 open, checks fail: x", text)
        self.assertIn("mergeable: mergeable (blocked), review: none", text)
        self.assertIn("checks: 1 fail, 1 pass, 1 pending", text)
        self.assertIn("fail    Tests  https://github.com/o/r/actions/runs/1/job/2", text)
        self.assertIn("pending Eval", text)


LABELS = """
[types.feat]
color = "1D76DB"
description = "Adds a capability"
[types.fix]
color = "d73a4a"
[areas.evals]
color = "fbca04"
paths = ["evals/", "light_labs/evals/"]
[areas.git]
color = "bfdadc"
paths = ["light_labs/gitops.py"]
[states.idea]
color = "c2e0c6"
[keep]
labels = ["dependencies"]
"""


class LabelsTest(RepoCase):
    def setUp(self):
        super().setUp()
        (self.path / ".github").mkdir()
        (self.path / ".github/labels.toml").write_text(LABELS)

    def test_labels_for_a_pr(self):
        labels, keep = gitops.load_labels(self.repo)
        self.assertEqual(keep, {"dependencies"})
        got = gitops.labels_for(
            "feat(evals): add a stage", ["evals/stages/x.yaml", "light_labs/gitops.py"], labels
        )
        self.assertEqual(got, ["type: feat", "area: evals", "area: git"])
        self.assertEqual(gitops.labels_for("Rename things", ["README.md"], labels), [])
        self.assertIn("state: idea", labels)
        self.assertNotIn("state: idea", gitops.labels_for("idea: x", ["evals/a"], labels))

    def test_sync_plans_create_update_and_prune_but_keeps_tool_labels(self):
        self.repo.responses[("label", "list")] = (
            '[{"name": "type: feat", "color": "1d76db", "description": "Adds a capability"},'
            '{"name": "type: fix", "color": "000000", "description": ""},'
            '{"name": "bug", "color": "d73a4a", "description": ""},'
            '{"name": "dependencies", "color": "0366d6", "description": ""}]'
        )
        changes = gitops.sync_labels(self.repo, prune=True, out=io.StringIO())
        plan = {(verb, name) for verb, name, _ in changes}
        self.assertEqual(
            plan,
            {("update", "type: fix"), ("create", "area: evals"), ("create", "area: git"),
             ("create", "state: idea"), ("delete", "bug")},
        )  # fmt: skip
        self.assertFalse(
            any(c[:2] in (("label", "create"), ("label", "delete")) for c in self.repo.calls)
        )

    def test_label_prs_adds_only_whats_missing(self):
        self.repo.responses[("pr", "view")] = (
            '{"title": "fix: x", "files": [{"path": "evals/a.go"}],'
            ' "labels": [{"name": "type: fix"}, {"name": "dependencies"}]}'
        )
        self.repo.responses[("label", "list")] = '[{"name": "area: evals"}, {"name": "type: fix"}]'
        added = gitops.label_prs(self.repo, [7], out=io.StringIO())
        self.assertEqual(added, {7: ["area: evals"]})
        edit = next(c for c in self.repo.calls if c[:2] == ("pr", "edit"))
        self.assertEqual(edit, ("pr", "edit", "7", "--add-label", "area: evals"))

    def test_labels_not_synced_yet_are_skipped_with_a_note(self):
        self.repo.responses[("pr", "view")] = '{"title": "feat: x", "files": [], "labels": []}'
        self.repo.responses[("label", "list")] = "[]"
        out = io.StringIO()
        self.assertEqual(gitops.label_prs(self.repo, [7], out=out), {7: []})
        self.assertIn("lab git labels --apply", out.getvalue())
        self.assertFalse(any(c[:2] == ("pr", "edit") for c in self.repo.calls))

    def test_no_labels_file_means_no_labelling(self):
        (self.path / ".github/labels.toml").unlink()
        self.assertEqual(gitops.label_prs(self.repo, [7], out=io.StringIO()), {})
        self.assertEqual(self.repo.calls, [])


class ChecksStateTest(unittest.TestCase):
    def test_rollup(self):
        ok = {"status": "COMPLETED", "conclusion": "SUCCESS"}
        self.assertEqual(gitops.checks_state([]), "none")
        self.assertEqual(gitops.checks_state([ok]), "pass")
        self.assertEqual(gitops.checks_state([ok, {"status": "IN_PROGRESS"}]), "pending")
        bad = {"status": "COMPLETED", "conclusion": "FAILURE"}
        self.assertEqual(gitops.checks_state([ok, bad, {"status": "QUEUED"}]), "fail")


if __name__ == "__main__":
    unittest.main()
