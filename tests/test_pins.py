import tempfile
import unittest
from datetime import date
from pathlib import Path

from light_labs import pins

TODAY = date(2026, 11, 15)


class PinsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def audit(self, newest=(3, 14)):
        return pins.audit(self.root, newest=newest, today=TODAY)

    def project(self, where="", requires=">=3.11", pin="3.13"):
        self.write(f"{where}pyproject.toml", f'[project]\nrequires-python = "{requires}"\n')
        if pin:
            self.write(f"{where}.python-version", f"{pin}\n")

    def test_a_project_without_a_pin_is_an_error_and_a_pin_above_it_counts(self):
        self.project("tools/a/", pin=None)
        self.assertIn("no .python-version", self.audit()["errors"][0])
        self.write(".python-version", "3.13\n")
        result = self.audit()
        self.assertEqual((result["errors"], result["pins"]), ([], {"tools/a": "3.13"}))

    def test_the_pin_must_be_major_minor_and_inside_requires_python(self):
        self.project(pin="3.13.3")
        self.assertIn("not major.minor", self.audit()["errors"][0])
        self.project(requires=">=3.13,<3.14", pin="3.14")
        self.assertIn("excludes its pin 3.14", self.audit()["errors"][0])
        self.assertTrue(pins.admits(">=3.13,<4.0", (3, 13)))

    def test_a_dockerfile_matches_the_pin_or_says_why_not(self):
        self.project()
        self.write("Dockerfile", "FROM python:3.11-slim AS base\n")
        self.assertIn("Dockerfile:1: image Python 3.11, pin 3.13", self.audit()["errors"][0])
        self.write(
            "Dockerfile", "# pin-exempt: tied to Airflow 2.8\nFROM apache/airflow:2.8-python3.11\n"
        )
        result = self.audit()
        self.assertEqual(result["errors"], [])
        self.assertIn("exempt: tied to Airflow 2.8", result["warnings"][0])
        self.write("Dockerfile", "FROM python:3.13-slim\n")
        self.assertFalse([w for w in self.audit()["warnings"] if "Dockerfile" in w])

    def test_ci_may_run_the_pin_the_floor_and_the_next_minor_only(self):
        self.project(requires=">=3.12")
        self.write(".github/workflows/ci.yml", 'matrix:\n  python: ["3.12", "3.13"]\n')
        self.write(".github/workflows/next.yml", 'python-version: "3.14"\n')
        self.assertEqual(self.audit()["errors"], [])
        self.write(".github/workflows/old.yml", "run: uv python install 3.10\n")
        self.assertIn("Python 3.10 is not a pin", self.audit()["errors"][0])

    def test_warnings_name_what_lags(self):
        self.project(requires=">=3.10", pin="3.12")
        warnings = "\n".join(self.audit()["warnings"])
        self.assertIn("floor 3.10 is end-of-life", warnings)
        self.assertIn("pinned to 3.12, 2 minors behind 3.14", warnings)
        self.assertIn("floor 3.10 is never run (pin 3.12)", warnings)
        self.project("b/", requires=">=3.10", pin="3.12")
        (line,) = [w for w in self.audit()["warnings"] if "never run" in w]
        self.assertTrue(line.endswith(": ., b"))  # one line per floor, not per project
        self.assertFalse(pins.end_of_life((3, 11), TODAY))
        self.assertEqual(self.audit()["errors"], [])

    def test_newest_stable_ignores_prereleases_and_a_missing_uv(self):
        out = "cpython-3.15.0a6-macos x\ncpython-3.14.7-macos y\ncpython-3.13.12-linux z\n"
        run = lambda *a, **k: type("R", (), {"stdout": out})()
        self.assertEqual(pins.newest_stable(run), (3, 14))

        def missing(*a, **k):
            raise FileNotFoundError

        self.assertIsNone(pins.newest_stable(missing))

    def test_the_lab_itself_passes(self):
        result = pins.audit(Path(pins.__file__).resolve().parents[1], today=TODAY)
        self.assertEqual(result["errors"], [])


if __name__ == "__main__":
    unittest.main()
