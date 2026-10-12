"""Eval results in DuckDB: the runner's JSONL files, landed in `raw.eval_samples`.

The JSONL files under var/evals stay the source of truth; `ingest` is idempotent per
run, so the database can be rebuilt from them at any time. This module is the EL step
only: the dbt project in analytics/ models staging and marts beside the raw schema
(`just analytics`). Plain SQL throughout, so it moves to Postgres when the lab outgrows
a file.
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
    "filter": "VARCHAR",
    "bar_min_fixture_rate": "DOUBLE",
    "bar_max_gap": "DOUBLE",
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

-- Stopgap views from before the dbt project; marts.fct_eval_runs replaces them.
DROP VIEW IF EXISTS main.eval_runs;
DROP VIEW IF EXISTS main.eval_categories;
"""

# Columns added after a database was first created: ADD COLUMN keeps old rows as NULL.
MIGRATE = "".join(
    f'ALTER TABLE raw.eval_samples ADD COLUMN IF NOT EXISTS "{name}" {kind};\n'
    for name, kind in COLUMNS.items()
)


def connect(db=None):
    import duckdb

    path = Path(db or DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA + MIGRATE)
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
            con.execute(
                "INSERT INTO raw.eval_samples BY NAME SELECT *, ? AS source FROM batch", [path.name]
            )
            for run_id, n in con.execute(
                "SELECT run_id, count(*) FROM batch GROUP BY 1"
            ).fetchall():
                loaded[run_id] = n
            con.execute("COMMIT")
    return loaded


def runs(stage=None, contestant=None, limit=20, db=None):
    """Most recent runs first from marts.fct_eval_runs, as (columns, rows)."""
    where, params = [], []
    if stage:
        where.append("stage = ?")
        params.append(stage)
    if contestant:
        where.append("contestant = ?")
        params.append(contestant)
    sql = (
        "SELECT run_id, contestant, brain, git_commit, is_dirty, is_full_run, sample_count, "
        "round(sample_pass_rate, 3) AS sample_pass_rate, "
        "round(fixture_pass_rate, 3) AS fixture_pass_rate, "
        "round(mean_latency_seconds, 2) AS mean_latency_seconds, "
        "round(total_cost_usd, 4) AS total_cost_usd "
        "FROM marts.fct_eval_runs"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY started_at DESC LIMIT ?"
    )
    with connect(db) as con:
        built = con.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'marts' AND table_name = 'fct_eval_runs'"
        ).fetchone()[0]
        if not built:
            raise LookupError("marts.fct_eval_runs is missing; run `just analytics`")
        cur = con.execute(sql, [*params, limit])
        return [d[0] for d in cur.description], cur.fetchall()
