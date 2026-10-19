import json
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess

from light_labs.agents.rush.github import notify
from light_labs.agents.rush.phone import PREFIX
from light_labs.core.store import Store

NOW = datetime(2026, 10, 18, 16, 0, tzinfo=UTC)
REPO = "pj/lab"


class FakeGH:
    """Stands in for subprocess.run on `gh`: answers from the fields below."""

    def __init__(self):
        self.runs = [run(1, "CI", "success")]
        self.dependabot, self.mine = [], []
        self.down = None

    def __call__(self, cmd, **kwargs):
        if self.down:
            raise self.down
        args = cmd[1:]
        if args[:2] == ["api", "user"]:
            out = {"login": "pj"}
        elif args[:2] == ["repo", "list"]:
            out = [
                {"nameWithOwner": REPO, "pushedAt": "2026-10-17T00:00:00Z",
                 "defaultBranchRef": {"name": "main"}},
                {"nameWithOwner": "pj/old", "pushedAt": "2025-01-01T00:00:00Z",
                 "defaultBranchRef": {"name": "main"}},
            ]  # fmt: skip
        elif args[:2] == ["run", "list"]:
            out = self.runs
        elif args[:2] == ["pr", "list"] and "app/dependabot" in args:
            out = self.dependabot
        elif args[:2] == ["pr", "list"]:
            out = self.mine
        else:
            raise AssertionError(f"unexpected gh {args}")
        return CompletedProcess(cmd, 0, stdout=json.dumps(out), stderr="")


def run(run_id, workflow, conclusion):
    return {"databaseId": run_id, "workflowName": workflow, "conclusion": conclusion,
            "url": f"https://gh/run/{run_id}"}  # fmt: skip


def pr(number, title, comments=(), reviews=()):
    return {"number": number, "title": title, "url": f"https://gh/pr/{number}",
            "comments": list(comments), "reviews": list(reviews)}  # fmt: skip


def note(login, at):
    return {"author": {"login": login}, "createdAt": at, "submittedAt": at}


class GitHubWatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.gh, self.sent = FakeGH(), []

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, to, text):
        self.sent.append(text)

    def check(self, quiet_hours=None, now=NOW):
        return notify(self.store, "me", self.send, quiet_hours=quiet_hours, run=self.gh, now=now)

    def test_first_check_records_without_texting(self):
        self.gh.dependabot = [pr(5, "bump x")]
        self.gh.mine = [pr(7, "feat", comments=[note("ketan", "2026-10-17T00:00:00Z")])]
        self.assertEqual(self.check(), [])
        self.assertEqual(self.sent, [])
        state = json.loads((self.store.root / "github.json").read_text())
        self.assertEqual(list(state["repos"]), [REPO])  # pj/old is not active

    def test_ci_breaking_and_recovering_are_one_message_each(self):
        self.check()
        self.gh.runs = [run(2, "CI", "failure")]
        [event] = self.check()
        self.assertIn("CI failed on pj/lab main (CI): https://gh/run/2", event)
        self.gh.runs = [run(3, "CI", "failure")]
        self.assertEqual(self.check(), [])  # still broken: no repeat
        self.gh.runs = [run(4, "CI", "success")]
        self.assertIn("passing again", self.check()[0])
        self.assertEqual(len(self.sent), 2)

    def test_new_dependabot_prs(self):
        self.gh.dependabot = [pr(5, "bump x")]
        self.check()
        self.gh.dependabot = [pr(6, "bump y"), pr(8, "bump z"), pr(5, "bump x")]
        [event] = self.check()
        self.assertEqual(event, "Dependabot on pj/lab: bump y (+1 more): https://gh/pr/6")

    def test_comments_by_others_on_pjs_prs(self):
        self.gh.mine = [pr(7, "feat", comments=[note("ketan", "2026-10-17T00:00:00Z")])]
        self.check()
        self.gh.mine = [
            pr(
                7,
                "feat",
                comments=[
                    note("ketan", "2026-10-17T00:00:00Z"),
                    note("pj", "2026-10-18T01:00:00Z"),
                    note("github-actions", "2026-10-18T02:00:00Z"),
                ],
                reviews=[note("muse", "2026-10-18T03:00:00Z")],
            )
        ]
        [event] = self.check()
        self.assertEqual(event, "muse reviewed on pj/lab#7 feat: https://gh/pr/7")
        self.assertEqual(self.check(), [])

    def test_several_events_are_one_digest(self):
        self.check()
        self.gh.runs = [run(2, "CI", "failure")]
        self.gh.dependabot = [pr(6, "bump y")]
        self.assertEqual(len(self.check()), 2)
        [text] = self.sent
        self.assertTrue(text.startswith(f"{PREFIX} GitHub, 2 updates:\n- "))

    def test_quiet_hours_skip_the_check(self):
        self.check()
        self.gh.runs = [run(2, "CI", "failure")]
        night = datetime(2026, 10, 18, 3, 0).astimezone()
        self.assertEqual(self.check(quiet_hours="0-8", now=night), [])
        self.assertEqual(self.sent, [])
        self.assertEqual(
            len(self.check(quiet_hours="0-8", now=datetime(2026, 10, 18, 9).astimezone())), 1
        )

    def test_gh_failure_is_journaled_not_raised(self):
        self.gh.down = FileNotFoundError("gh")
        self.assertEqual(self.check(), [])
        self.gh.down = subprocess.CalledProcessError(1, "gh", stderr="HTTP 502")
        self.assertEqual(self.check(), [])
        journal = (self.store.root / "journal.md").read_text()
        self.assertEqual(journal.count("GitHub check failed"), 2)
        self.assertIn("HTTP 502", journal)


if __name__ == "__main__":
    unittest.main()
