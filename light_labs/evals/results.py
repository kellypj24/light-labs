"""Eval results in DuckDB: the runner's JSONL files, loaded into one queryable table.

The JSONL files under var/evals stay the source of truth; `ingest` is idempotent per
run, so the database can be rebuilt from them at any time. Plain SQL throughout, so the
same schema moves to Postgres when the lab outgrows a file.

Layers follow the data-engineering toolkit: `raw.eval_samples` is the landed data, as the
runner wrote it. The two views are stopgaps for `lab evals runs` until a dbt project
models staging and marts on top of the raw table.
"""

from pathlib import Path

from light_labs import config

DB = config.VAR / "lab.duckdb"
RESULTS = config.VAR / "evals"

# Explicit types: keys missing from older files load as NULL instead of shifting types.
COLUMNS = {
    "run_id": "VARCHAR",
    "commit": "VARCHAR",
    "dirty": "BOOLEAN",
    "contestant": "VARCHAR",
    "role": "VARCHAR",
    "brain": "VARCHAR",
    "stage": "VARCHAR",
    "fixture": "VARCHAR",
    "category": "VARCHAR",
    "sample": "INTEGER",
    "passed": "BOOLEAN",
    "checks": "JSON",
    "draft": "VARCHAR",
    "escalate": "VARCHAR",
    "latency_s": "DOUBLE",
    "cost_usd": "DOUBLE",
    "isolated": "BOOLEAN",
    "error": "VARCHAR",
    "at": "TIMESTAMPTZ",
}

SCHEMA = f"""
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.eval_samples (
    {", ".join(f'"{name}" {kind}' for name, kind in COLUMNS.items())},
    source VARCHAR NOT NULL
);

-- One row per contestant per run.
CREATE OR REPLACE VIEW eval_runs AS
WITH fixtures AS (
    SELECT run_id, contestant, fixture, bool_and(passed) AS all_passed
    FROM raw.eval_samples GROUP BY ALL
)
SELECT
    s.run_id, s.stage, s.contestant, s.role, s.brain,
    any_value(s.commit) AS commit, bool_or(s.dirty) AS dirty,
    min(s.at) AS started,
    count(*) AS samples,
    count(*) FILTER (WHERE s.passed) AS passed,
    round(count(*) FILTER (WHERE s.passed) / count(*), 3) AS pass_rate,
    (SELECT round(avg(f.all_passed::INT), 3) FROM fixtures f
     WHERE f.run_id = s.run_id AND f.contestant = s.contestant) AS fixture_rate,
    round(avg(s.latency_s), 2) AS mean_latency_s,
    round(sum(s.cost_usd), 4) AS cost_usd,
    bool_and(coalesce(s.isolated, true)) AS isolated
FROM raw.eval_samples s
GROUP BY s.run_id, s.stage, s.contestant, s.role, s.brain;

-- Pass rate per category, per contestant, per run.
CREATE OR REPLACE VIEW eval_categories AS
SELECT run_id, stage, contestant, category,
    count(*) AS samples,
    count(*) FILTER (WHERE passed) AS passed,
    round(count(*) FILTER (WHERE passed) / count(*), 3) AS pass_rate
FROM raw.eval_samples GROUP BY ALL;
"""


def connect(db=None):
    import duckdb

    path = Path(db or DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    return con


def ingest(paths=None, db=None):
    """Load JSONL result files, replacing any earlier load of the same run.

    Files written before the runner stamped `run_id` use their file name instead.
    Returns {run_id: rows}.
    """
    paths = sorted(Path(p) for p in paths) if paths else sorted(RESULTS.glob("*.jsonl"))
    loaded = {}
    with connect(db) as con:
        for path in paths:
            if path.stat().st_size == 0:
                continue
            cols = ", ".join(f"'{name}': '{kind}'" for name, kind in COLUMNS.items())
            rows = f"read_json(?, format = 'newline_delimited', columns = {{{cols}}})"
            con.execute("BEGIN")
            con.execute(
                f"CREATE OR REPLACE TEMP TABLE batch AS SELECT * REPLACE "
                f"(coalesce(run_id, ?) AS run_id) FROM {rows}",
                [path.stem, str(path)],
            )
            con.execute("DELETE FROM raw.eval_samples WHERE run_id IN (SELECT run_id FROM batch)")
            con.execute("INSERT INTO raw.eval_samples SELECT *, ? FROM batch", [path.name])
            for run_id, n in con.execute("SELECT run_id, count(*) FROM batch GROUP BY 1").fetchall():
                loaded[run_id] = n
            con.execute("COMMIT")
    return loaded


def runs(stage=None, contestant=None, limit=20, db=None):
    """Most recent runs first, as (columns, rows)."""
    where, params = [], []
    if stage:
        where.append("stage = ?")
        params.append(stage)
    if contestant:
        where.append("contestant = ?")
        params.append(contestant)
    sql = (
        "SELECT run_id, contestant, brain, commit, dirty, samples, pass_rate, fixture_rate, "
        "mean_latency_s, cost_usd FROM eval_runs"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY started DESC LIMIT ?"
    )
    with connect(db) as con:
        cur = con.execute(sql, [*params, limit])
        return [d[0] for d in cur.description], cur.fetchall()
