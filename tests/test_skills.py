import json
import tempfile
import unittest
from pathlib import Path

from light_labs import config
from light_labs.core import skills

AUDIENCES = {"robots", "auto"}


def write_skill(root, name, front, body="Body text."):
    d = Path(root) / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\n{front}\n---\n\n{body}\n")


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parses_frontmatter_lists_and_body(self):
        write_skill(
            self.root,
            "alpha",
            "name: alpha\ndescription: does alpha things\naudience: [robots, auto]\n"
            "load: always\ntriggers: [build, 'code']",
        )
        s = skills.discover(self.root)["alpha"]
        self.assertEqual(s.audience, ["robots", "auto"])
        self.assertEqual(s.triggers, ["build", "code"])
        self.assertEqual(s.load, "always")
        self.assertEqual(s.body, "Body text.")

    def test_defaults_and_scalar_audience(self):
        write_skill(self.root, "beta", "name: beta\ndescription: d\naudience: auto")
        s = skills.discover(self.root)["beta"]
        self.assertEqual((s.audience, s.load, s.triggers), (["auto"], "on-match", []))

    def test_missing_frontmatter_or_fields(self):
        (self.root / "bad").mkdir()
        (self.root / "bad" / "SKILL.md").write_text("no frontmatter")
        with self.assertRaises(ValueError):
            skills.discover(self.root)
        (self.root / "bad" / "SKILL.md").write_text("---\nname: bad\n---\nbody")
        with self.assertRaises(ValueError):
            skills.discover(self.root)

    def test_for_robot_rejects_unknown(self):
        write_skill(self.root, "alpha", "name: alpha\ndescription: d")
        self.assertEqual([s.name for s in skills.for_robot(["alpha"], self.root)], ["alpha"])
        with self.assertRaises(KeyError):
            skills.for_robot(["alpha", "ghost"], self.root)


class RenderTest(unittest.TestCase):
    def setUp(self):
        def mk(name, load, triggers=()):
            return skills.Skill(
                name=name,
                description=f"{name} desc",
                body=f"{name} BODY",
                path=Path(name),
                load=load,
                triggers=list(triggers),
            )

        self.skills = [mk("always-on", "always"), mk("coder", "on-match", ["code", "script"])]

    def test_always_loaded_on_match_indexed(self):
        out = skills.render(self.skills, "hello there")
        self.assertIn("always-on BODY", out)
        self.assertNotIn("coder BODY", out)
        self.assertIn("- coder: coder desc", out)

    def test_trigger_loads_skill(self):
        out = skills.render(self.skills, "could you write a Script for this?")
        self.assertIn("coder BODY", out)
        self.assertNotIn("Other skills", out)

    def test_trigger_matches_word_start_only(self):
        self.assertNotIn("coder BODY", skills.render(self.skills, "a barcode reader"))

    def test_empty(self):
        self.assertEqual(skills.render([], "x"), "")


class RepoSkillsTest(unittest.TestCase):
    """Every skill in the repo is valid, and every robot's skills exist and suit robots."""

    def test_repo_skills_are_valid(self):
        found = skills.discover()
        self.assertTrue(found)
        for name, s in found.items():
            with self.subTest(skill=name):
                self.assertEqual(s.path.parent.name, name, "directory must match name")
                self.assertTrue(s.audience, "audience is required")
                self.assertLessEqual(set(s.audience), AUDIENCES)
                self.assertIn(s.load, {"always", "on-match"})
                if s.load == "on-match" and "robots" in s.audience:
                    self.assertTrue(s.triggers, "robot on-match skills need triggers")

    def test_registry_skills_exist_and_target_robots(self):
        found = skills.discover()
        for robot in json.loads(config.DLN.read_text())["robots"]:
            for name in robot.get("skills", []):
                with self.subTest(robot=robot["name"], skill=name):
                    self.assertIn(name, found)
                    self.assertIn("robots", found[name].audience)

    def test_robot_always_skills_stay_small(self):
        # Always-loaded skills cost context on every call to a small local model.
        for s in skills.discover().values():
            if "robots" in s.audience and s.load == "always":
                with self.subTest(skill=s.name):
                    self.assertLess(len(s.body), 2000)


class RushPromptTest(unittest.TestCase):
    def test_rush_prompt_has_persona_memory_and_skills(self):
        from light_labs.agents import rush

        prompt = rush.system_prompt("hello")
        self.assertIn("You are Rush (DLN-100)", prompt)
        self.assertIn("What Rush knows", prompt)
        self.assertIn("## agent-net-etiquette", prompt)
        self.assertIn("ESCALATE:", prompt)


if __name__ == "__main__":
    unittest.main()
