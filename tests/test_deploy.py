import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from light_labs import deploy


def sh(cwd, *cmd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class DeployCase(unittest.TestCase):
    """A real origin and checkout; `uv sync` is skipped (sync=False)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        remote = root / "remote.git"
        sh(root, "git", "init", "-q", "--bare", "-b", "main", str(remote))
        self.src = root / "work"
        sh(root, "git", "clone", "-q", str(remote), str(self.src))
        for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
            sh(self.src, "git", "config", k, v)
        self.commit("app.py", "v1")
        (self.src / ".env").write_text("LAB_EDGE=x\n")
        self.target = root / "deployed"

    def commit(self, name, text, branch="main"):
        (self.src / name).write_text(text)
        sh(self.src, "git", "add", name)
        sh(self.src, "git", "commit", "-q", "-m", text)
        sh(self.src, "git", "push", "-q", "origin", f"HEAD:{branch}")
        return sh(self.src, "git", "rev-parse", "HEAD")

    def deploy(self, ref="main"):
        return deploy.deploy(self.target, ref, source=self.src, sync=False, out=io.StringIO())

    def test_exports_the_commit_without_git_and_links_local_files(self):
        stamp = self.deploy()
        current = self.target / "current"
        self.assertEqual((current / "app.py").read_text(), "v1")
        self.assertFalse((current / ".git").exists())
        self.assertTrue((current / ".env").is_symlink())
        self.assertEqual(json.loads((current / deploy.STAMP).read_text())["sha"], stamp["sha"])

    def test_checkout_changes_do_not_reach_the_release(self):
        self.deploy()
        (self.src / "app.py").write_text("uncommitted")
        sh(self.src, "git", "checkout", "-q", "-b", "feature/x")
        self.assertEqual((self.target / "current" / "app.py").read_text(), "v1")

    def test_branch_deploy_then_back_to_main(self):
        self.deploy()
        self.commit("app.py", "branch", branch="feature/x")
        self.assertEqual(self.deploy("feature/x")["ref"], "feature/x")
        self.assertEqual((self.target / "current" / "app.py").read_text(), "branch")
        self.deploy("main")
        self.assertEqual((self.target / "current" / "app.py").read_text(), "v1")

    def test_keeps_the_newest_releases(self):
        for i in range(deploy.KEEP + 2):
            self.commit("app.py", f"v{i + 2}")
            self.deploy()
        self.assertEqual(len(list((self.target / "releases").iterdir())), deploy.KEEP)
        self.assertEqual((self.target / "current" / "app.py").read_text(), f"v{deploy.KEEP + 3}")

    def test_unknown_ref_fails_and_leaves_current(self):
        self.deploy()
        with self.assertRaises(deploy.DeployError):
            self.deploy("nope")
        self.assertEqual((self.target / "current" / "app.py").read_text(), "v1")

    def test_failed_build_is_removed(self):
        with (
            mock.patch.object(deploy, "_build", side_effect=deploy.DeployError("uv sync")),
            self.assertRaises(deploy.DeployError),
        ):
            self.deploy()
        self.assertEqual(list((self.target / "releases").iterdir()), [])
        self.assertFalse((self.target / "current").exists())

    def test_redeploy_main_skips_a_branch_deploy(self):
        self.commit("app.py", "branch", branch="feature/x")
        self.deploy("feature/x")
        out = io.StringIO()
        with mock.patch.dict(deploy.TARGETS, {"hermes": self.target}, clear=True):
            self.assertEqual(deploy.redeploy_main("main", out=out), [])
        self.assertIn("stays on feature/x", out.getvalue())

    def test_redeploy_main_follows_main(self):
        self.deploy()
        self.commit("app.py", "v2")
        with mock.patch.dict(deploy.TARGETS, {"hermes": self.target}, clear=True):
            done = deploy.redeploy_main("main", out=io.StringIO(), source=self.src, sync=False)
        self.assertEqual(done, ["hermes"])
        self.assertEqual((self.target / "current" / "app.py").read_text(), "v2")
