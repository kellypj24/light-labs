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

    def deploy(self, ref="main", restart=None):
        return deploy.deploy(
            self.target, ref, source=self.src, sync=False, restart=restart, out=io.StringIO()
        )

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
        marker = self.target / "restarted"
        with (
            mock.patch.dict(deploy.TARGETS, {"hermes": self.target}, clear=True),
            mock.patch.dict(deploy.RESTART, {"hermes": ("touch", str(marker))}, clear=True),
        ):
            done = deploy.redeploy_main("main", out=io.StringIO(), source=self.src, sync=False)
        self.assertEqual(done, ["hermes"])
        self.assertEqual((self.target / "current" / "app.py").read_text(), "v2")
        self.assertTrue(marker.exists())

    def test_a_deploy_from_a_worktree_links_the_main_checkouts_files(self):
        wt = self.src.parent / "wt"
        sh(self.src, "git", "worktree", "add", "-q", "--detach", str(wt))
        deploy.deploy(self.target, source=wt, sync=False, out=io.StringIO())
        env = self.target / "current" / ".env"
        self.assertEqual(env.resolve(), (self.src / ".env").resolve())
        # A link left dangling by an older deploy is repaired on the next one.
        env.unlink()
        env.symlink_to(wt / ".env")
        self.assertFalse(env.exists())
        deploy.deploy(self.target, source=wt, sync=False, out=io.StringIO())
        self.assertEqual(env.read_text(), "LAB_EDGE=x\n")

    def test_a_targets_groups_are_installed_with_the_release(self):
        real, synced = deploy._run, []

        def run(*cmd, cwd=None):
            if cmd[:2] == ("uv", "sync"):
                synced.append(cmd)
                return b""
            return real(*cmd, cwd=cwd)

        with mock.patch.object(deploy, "_run", run):
            deploy.deploy(
                self.target, source=self.src, out=io.StringIO(), groups=("orchestration",)
            )
        self.assertEqual(
            synced[0][2:7], ("--locked", "--no-dev", "--group", "orchestration", "--project")
        )

    def test_rollback_goes_to_the_release_before_and_restarts(self):
        self.deploy()
        with self.assertRaisesRegex(deploy.DeployError, "no earlier release"):
            deploy.rollback(self.target, out=io.StringIO())
        self.commit("app.py", "v2")
        with mock.patch.object(deploy, "datetime") as clock:  # stamps a second apart
            clock.now.return_value.isoformat.return_value = "2099-01-01T00:00:00+00:00"
            self.deploy()
        self.assertEqual((self.target / "current" / "app.py").read_text(), "v2")
        restarted, out = [], io.StringIO()
        stamp = deploy.rollback(self.target, restart=restarted.append, out=out)
        self.assertEqual((self.target / "current" / "app.py").read_text(), "v1")
        self.assertEqual(restarted, [out])
        self.assertIn(f"rolled back to main {stamp['sha'][:12]}", out.getvalue())
        self.deploy()  # the next deploy of main moves forward again
        self.assertEqual((self.target / "current" / "app.py").read_text(), "v2")

    def lab_restart(self, ps, loaded=("rush-remote", "dagster")):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            out = ""
            if cmd[:2] == ["launchctl", "list"]:
                name = cmd[2].rsplit(".", 1)[1]
                out = '{\n\t"PID" = 77;\n};\n' if name in loaded else "{\n};\n"
            elif cmd[0] == "ps":
                out = "Mon Nov  9 21:27:23 2026\n"
            return mock.Mock(returncode=0, stdout=out)

        out = io.StringIO()
        deploy.restart_lab(out, run=run, ps=ps)
        return [c[3].rsplit(".", 1)[1] for c in calls if c[:2] == ["launchctl", "kickstart"]], out

    def test_the_lab_restart_spares_a_dagster_run_and_unloaded_jobs(self):
        idle = "  1  0.0 /usr/bin/python3 dagster-daemon run\n"
        self.assertEqual(self.lab_restart(idle)[0], ["rush-remote", "dagster"])
        busy = idle + " 9  50.0 /x/python -m dagster api execute_run {}\n"
        kicked, out = self.lab_restart(busy)
        self.assertEqual(kicked, ["rush-remote"])
        self.assertIn("a run is in progress; `just dagster-restart`", out.getvalue())
        kicked, out = self.lab_restart(idle, loaded=("dagster",))
        self.assertEqual(kicked, ["dagster"])
        self.assertIn("rush-remote: not running, left alone", out.getvalue())

    def test_a_redeploy_takes_the_verified_commit_not_what_main_reached_since(self):
        self.deploy()
        verified = self.commit("app.py", "v2")
        newer = self.commit("app.py", "v3")  # merged while v2's CI ran; not verified yet
        with mock.patch.dict(deploy.TARGETS, {"hermes": self.target}, clear=True):
            out = io.StringIO()
            deploy.redeploy_main("main", out=out, sha=verified, source=self.src, sync=False)
            self.assertEqual((self.target / "current" / "app.py").read_text(), "v2")
            deploy.redeploy_main("main", out=out, sha=newer, source=self.src, sync=False)
            self.assertEqual((self.target / "current" / "app.py").read_text(), "v3")
            # v2's land finishing late doesn't take the target backwards.
            done = deploy.redeploy_main("main", out=out, sha=verified, source=self.src, sync=False)
        self.assertEqual(done, [])
        self.assertIn(f"hermes is already at or past {verified[:12]}", out.getvalue())
        self.assertEqual((self.target / "current" / "app.py").read_text(), "v3")

    def test_a_commit_that_is_not_on_the_branch_is_refused(self):
        self.deploy()
        stray = self.commit("app.py", "branch", branch="feature/x")
        sh(self.src, "git", "reset", "-q", "--hard", "origin/main")
        with self.assertRaisesRegex(deploy.DeployError, "is not on origin/main"):
            deploy.deploy(self.target, source=self.src, sync=False, out=io.StringIO(), sha=stray)

    def test_one_failed_target_does_not_stop_the_next(self):
        self.deploy()
        other = self.target.parent / "other"
        deploy.deploy(other, source=self.src, sync=False, out=io.StringIO())
        self.commit("app.py", "v2")
        real = deploy.deploy

        def flaky(target, *args, **kw):
            if target == self.target:
                raise deploy.DeployError("git fetch: Connection reset")
            return real(target, *args, **kw)

        with (
            mock.patch.dict(deploy.TARGETS, {"hermes": self.target, "radar": other}, clear=True),
            mock.patch.object(deploy, "deploy", flaky),
            self.assertRaisesRegex(deploy.DeployError, r"hermes: .*retry: `lab deploy hermes`"),
        ):
            deploy.redeploy_main("main", out=io.StringIO(), source=self.src, sync=False)
        self.assertEqual((other / "current" / "app.py").read_text(), "v2")
        self.assertEqual((self.target / "current" / "app.py").read_text(), "v1")

    def test_a_dropped_fetch_is_retried(self):
        real, calls, naps = deploy._run, [], []

        def run(*cmd, cwd=None):
            if "fetch" in cmd:
                calls.append(cmd)
                if len(calls) < 3:
                    raise deploy.DeployError("git fetch: Connection reset by peer")
            return real(*cmd, cwd=cwd)

        with mock.patch.object(deploy, "_run", run):
            deploy.deploy(
                self.target, source=self.src, sync=False, out=io.StringIO(), sleep=naps.append
            )
            self.assertEqual(naps, [2, 4])
        always = mock.patch.object(deploy, "_run", side_effect=deploy.DeployError("reset"))
        with always as failing, self.assertRaises(deploy.DeployError):
            deploy._fetch(self.src, sleep=lambda s: None)
        self.assertEqual(failing.call_count, deploy.FETCH_TRIES)

    def test_stale_services_are_the_running_ones_the_merge_touched(self):
        def run(cmd, **kw):
            out = ""
            if cmd[:2] == ["launchctl", "list"]:
                out = '{\n\t"PID" = 4242;\n};\n' if cmd[2].endswith("dagster") else "{\n};\n"
            elif cmd[0] == "ps":
                out = "Mon Nov  9 21:27:23 2026\n"
            return mock.Mock(returncode=0, stdout=out)

        stale = deploy.stale_services(["analytics/models/x.sql", "docs/a.md"], run)
        self.assertEqual(
            [(n, f"{t:%b %-d %H:%M}") for n, t, _ in stale], [("dagster", "Nov 9 21:27")]
        )
        self.assertEqual(deploy.stale_services(["docs/a.md"], run), [])

    def test_restarts_only_when_the_commit_changes(self):
        marker = self.target / "restarted"
        self.deploy(restart=("touch", str(marker)))
        self.assertTrue(marker.exists())
        marker.unlink()
        self.deploy(restart=("touch", str(marker)))
        self.assertFalse(marker.exists())

    def test_a_failed_restart_keeps_the_new_release(self):
        self.deploy()
        self.commit("app.py", "v2")
        with self.assertRaisesRegex(deploy.DeployError, "but `false` failed"):
            self.deploy(restart=("false",))
        self.assertEqual((self.target / "current" / "app.py").read_text(), "v2")
