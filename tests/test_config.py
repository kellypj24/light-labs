import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from light_labs import config
from light_labs.core.agentnet import Client


class LoadEnvTest(unittest.TestCase):
    def test_reads_file_without_overriding(self):
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text("# comment\nLAB_T1=from-file\nLAB_T2='quoted'\n\nnot a pair\n")
            with mock.patch.dict(os.environ, {"LAB_T1": "already-set"}, clear=False):
                config.load_env(env)
                self.assertEqual(os.environ["LAB_T1"], "already-set")
                self.assertEqual(os.environ["LAB_T2"], "quoted")
            os.environ.pop("LAB_T2", None)

    def test_missing_file_is_fine(self):
        config.load_env(Path("/nonexistent/.env"))


class ClientTest(unittest.TestCase):
    def test_requires_edge(self):
        with self.assertRaises(RuntimeError):
            Client(base="")

    def test_strips_trailing_slash(self):
        self.assertEqual(
            Client(base="https://edge.example/", token="t").base, "https://edge.example"
        )


class RegistryTest(unittest.TestCase):
    def test_rush_is_dln_100(self):
        self.assertEqual(config.robot("rush")["dln"], "DLN-100")

    def test_unknown_robot(self):
        with self.assertRaises(KeyError):
            config.robot("wily")
