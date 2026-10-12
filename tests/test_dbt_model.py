import importlib.util
import unittest

from light_labs.agents.guts_man.builder import extract_sql, model_prompt
from light_labs.evals import dbt_model

HAS_DBT = importlib.util.find_spec("dbt") is not None

FIXTURE = {
    "target": "run_fixture_pass_rate",
    "upstream": ["stg_eval_samples"],
    "task": "One row per run and contestant: share of fixtures where every sample passed.",
    "reference": """
        WITH fixtures AS (
            SELECT run_id, contestant, fixture, BOOL_AND(is_passed) AS ok
            FROM {{ ref('stg_eval_samples') }}
            GROUP BY run_id, contestant, fixture
        )
        SELECT run_id, contestant,
            COUNT(*) FILTER (WHERE ok)::DOUBLE / COUNT(*) AS fixture_pass_rate
        FROM fixtures GROUP BY run_id, contestant
    """,
}


class FakeBrain:
    def __init__(self, answer):
        self.answer, self.last = answer, {}

    def think(self, system, user, temperature=None):
        self.system, self.user = system, user
        self.last = {"latency_s": 0.1}
        return self.answer


class BuilderTest(unittest.TestCase):
    def test_extract_sql(self):
        self.assertEqual(extract_sql("Here you go:\n```sql\nSELECT 1;\n```\nDone."), "SELECT 1")
        self.assertEqual(extract_sql("SELECT 1;\n"), "SELECT 1")
        self.assertEqual(extract_sql("```\nSELECT 2\n```"), "SELECT 2")

    def test_prompt_lists_upstream_columns(self):
        upstream = [
            {
                "name": "stg_x",
                "description": "One row per x.",
                "columns": [{"name": "x_id", "type": "VARCHAR", "description": "Key"}],
            }
        ]
        prompt = model_prompt("x_counts", "Count x.", upstream)
        self.assertIn("`x_counts`", prompt)
        self.assertIn("- x_id VARCHAR: Key", prompt)
        self.assertIn("### {{ ref('stg_x') }}", prompt)
        self.assertIn("FROM {{ ref('stg_x') }}", prompt)
        self.assertIn("models/x_counts.sql", prompt)


class SyntheticDataTest(unittest.TestCase):
    def test_deterministic_and_shaped_for_the_traps(self):
        rows = dbt_model.synthetic_samples()
        self.assertEqual(rows, dbt_model.synthetic_samples())
        errors = {r["brain"] for r in rows if r["checks"][0]["passed"] is False}
        self.assertNotIn("claude:sonnet", errors)  # a brain with no harness errors
        self.assertTrue(any("filter" in r for r in rows))
        self.assertTrue(any("commit" not in r for r in rows))
        self.assertEqual(len({r["at"] for r in rows}), len(rows))  # no timestamp ties


@unittest.skipUnless(HAS_DBT, "needs the analytics dependency group")
class RunSampleTest(unittest.TestCase):
    def run_with(self, answer):
        return dbt_model.run_sample(FakeBrain(answer), FIXTURE)

    def test_reference_answer_passes(self):
        result = self.run_with(FIXTURE["reference"])
        self.assertEqual(
            result["flags"], {"sql": True, "builds": True, "columns": True, "rows": True}
        )

    def test_one_level_aggregate_fails_on_rows(self):
        # The grain trap: a sample rate, not a fixture rate.
        result = self.run_with(
            "SELECT run_id, contestant, AVG(is_passed::INT) AS fixture_pass_rate "
            "FROM {{ ref('stg_eval_samples') }} GROUP BY run_id, contestant"
        )
        self.assertTrue(result["flags"]["builds"] and result["flags"]["columns"])
        self.assertFalse(result["flags"]["rows"])

    def test_wrong_column_name_fails_on_columns(self):
        result = self.run_with(FIXTURE["reference"].replace("fixture_pass_rate", "rate"))
        self.assertFalse(result["flags"]["columns"])
        self.assertIn("missing ['fixture_pass_rate']", result["notes"])

    def test_broken_sql_and_jinja_are_the_robots_failure(self):
        for answer in ("SELEC nonsense FROM", "SELECT {{ ref('stg_eval_samples' }}"):
            result = self.run_with(answer)
            self.assertFalse(result["flags"]["builds"], answer)
            self.assertTrue(result["notes"], answer)

    def test_no_file_access_from_candidate_sql(self):
        result = self.run_with("SELECT * FROM read_csv('/etc/hosts')")
        self.assertFalse(result["flags"]["builds"])


if __name__ == "__main__":
    unittest.main()
