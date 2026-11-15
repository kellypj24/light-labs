"""The launchd jobs in ops/: each plist parses and its command still exists. A renamed
CLI command or just recipe would otherwise break a scheduled job with no test failing."""

import io
import plistlib
import re
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from light_labs import cli, deploy

REPO = Path(__file__).resolve().parents[1]
PLISTS = sorted((REPO / "ops").glob("*.plist"))
PJ_HOME = "/Users/pjkelly"


class LaunchdJobsTest(unittest.TestCase):
    def jobs(self):
        self.assertTrue(PLISTS)
        return [(path, plistlib.loads(path.read_bytes())) for path in PLISTS]

    def test_each_label_matches_its_file(self):
        for path, job in self.jobs():
            self.assertEqual(job["Label"], path.stem)

    def test_each_command_is_one_the_repo_still_has(self):
        recipes = set(
            re.findall(r"^([a-z][\w-]*)[^\n:]*:", (REPO / "justfile").read_text(), re.MULTILINE)
        )
        for _, job in self.jobs():
            argv = job["ProgramArguments"]
            if "lab" in argv:
                args = argv[argv.index("lab") + 1 :]
                try:
                    with redirect_stderr(io.StringIO()) as err:
                        cli.parser().parse_args(args)
                except SystemExit:
                    self.fail(f"`lab {' '.join(args)}` no longer parses: {err.getvalue()}")
            elif Path(argv[0]).name == "just":
                self.assertIn(argv[-1], recipes)
            else:
                self.fail(f"unknown kind of job: {argv}")

    def test_each_job_runs_the_deployed_release_against_the_checkouts_var(self):
        # The plists name PJ's home outright; the target is under whoever runs the tests.
        target = deploy.TARGETS["lab"].relative_to(Path.home())
        current = f"{PJ_HOME}/{target}/current"
        for path, job in self.jobs():
            with self.subTest(path.name):
                argv = job["ProgramArguments"]
                self.assertTrue(
                    any(a == current or a.startswith(current + "/") for a in argv), argv
                )
                self.assertNotIn(f"{PJ_HOME}/light-labs", argv)  # never the live checkout
                env = job["EnvironmentVariables"]
                self.assertEqual(env["LAB_VAR"], f"{PJ_HOME}/light-labs/var")
                # A release's environment is built once at deploy; a tick never installs.
                self.assertTrue("--no-sync" in argv or env.get("UV_NO_SYNC") == "1", argv)

    def test_the_services_a_merge_reports_are_the_keep_alive_jobs(self):
        keep_alive = {job["Label"] for _, job in self.jobs() if job.get("KeepAlive")}
        self.assertEqual({s["label"] for s in deploy.SERVICES.values()}, keep_alive)


if __name__ == "__main__":
    unittest.main()
