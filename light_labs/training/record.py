"""PJ's notes, the weekly plans and the Workouts app's check-offs landed in DuckDB, for
the planned-versus-done marts.

`raw.training_notes`: one row per thing a note said (`training.notes`), every note kept,
voided ones flagged. `raw.training_plan_days`: one row per day of each plan in
var/training/plans/*.json, as it stood when last planned, and `raw.training_plan_items`:
one row per item of those days. `raw.training_checks`: one row per tap in the Workouts
app (`training.checks`), undoings included. All are snapshot replaces of small local
files (`lab training ingest-notes`, `ingest-plans`, `ingest-plan-items`, `ingest-checks`;
Dagster's `raw/training_*` assets).

The note text and each row's `what` are in the raw table and staging only. They stay out
of the marts the planner reads, so they never reach its Claude call.
"""

import json
from datetime import datetime
from pathlib import Path

from light_labs import config
from light_labs.evals import results
from light_labs.training import checks, notes

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE TABLE IF NOT EXISTS raw.training_notes (
    note_id VARCHAR NOT NULL,
    row_index INTEGER NOT NULL,
    noted_at TIMESTAMP NOT NULL,
    kind VARCHAR NOT NULL,
    note_date DATE NOT NULL,
    end_date DATE,
    start_time VARCHAR,
    end_time VARCHAR,
    minutes INTEGER,
    effort VARCHAR,
    is_done BOOLEAN NOT NULL,
    what VARCHAR,
    note_text VARCHAR NOT NULL,
    model VARCHAR,
    wants_replan BOOLEAN NOT NULL,
    is_voided BOOLEAN NOT NULL,
    PRIMARY KEY (note_id, row_index)
);
CREATE TABLE IF NOT EXISTS raw.training_plan_days (
    plan_date DATE PRIMARY KEY,
    iso_week VARCHAR NOT NULL,
    is_rest BOOLEAN NOT NULL,
    slot_start VARCHAR,
    slot_end VARCHAR,
    session_type VARCHAR,
    title VARCHAR,
    is_outdoor BOOLEAN,
    item_count INTEGER NOT NULL,
    planned_at TIMESTAMP NOT NULL,
    source_file VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS raw.training_plan_items (
    plan_date DATE NOT NULL,
    item_index INTEGER NOT NULL,
    iso_week VARCHAR NOT NULL,
    item_key VARCHAR NOT NULL,
    label VARCHAR NOT NULL,
    exercise VARCHAR,
    sets INTEGER,
    reps INTEGER,
    load_lb DOUBLE,
    unit_count INTEGER NOT NULL,
    PRIMARY KEY (plan_date, item_index)
);
CREATE TABLE IF NOT EXISTS raw.training_checks (
    line_index INTEGER PRIMARY KEY,
    checked_at TIMESTAMP NOT NULL,
    plan_date DATE NOT NULL,
    item_key VARCHAR NOT NULL,
    set_number INTEGER NOT NULL,
    is_done BOOLEAN NOT NULL
);
"""


def note_rows(path):
    """One tuple per row of every note in a notes.jsonl, voided ones included. A note
    not read yet (saved in work hours) has no rows and is left out until it is."""
    out = []
    for note in notes.history(path):
        for i, r in enumerate(note["rows"] or []):
            out.append(
                (
                    note["id"],
                    i,
                    datetime.fromisoformat(note["at"]),
                    r["kind"],
                    r["date"],
                    r["end_date"],
                    r["start"],
                    r["end"],
                    r["minutes"],
                    r["effort"],
                    r["done"],
                    r["what"],
                    note["text"],
                    note["model"],
                    bool(note.get("replan")),
                    note["voided"],
                )
            )
    return out


def plan_rows(path):
    """One tuple per day of a plan's JSON (var/training/plans/<iso week>.json)."""
    path = Path(path)
    planned_at = datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0)
    out = []
    for d in json.loads(path.read_text()).get("days", []):
        slot = d.get("slot") or [None, None]
        out.append(
            (
                d["date"],
                path.stem,
                bool(d.get("rest")),
                slot[0],
                slot[1],
                d.get("type"),
                d.get("title"),
                d.get("outdoor"),
                len(d.get("items") or []),
                planned_at,
                str(path),
            )
        )
    return out


def _replace(table, rows, db):
    with results.connect(db) as con:
        con.execute(SCHEMA)
        con.execute("BEGIN")
        con.execute(f"DELETE FROM raw.{table}")
        if rows:
            marks = ", ".join("?" for _ in rows[0])
            con.executemany(f"INSERT INTO raw.{table} VALUES ({marks})", rows)
        con.execute("COMMIT")
    return len(rows)


def ingest_notes(path=None, var=None, db=None):
    """Reload raw.training_notes from notes.jsonl. Returns the row count."""
    return _replace("training_notes", note_rows(path or notes.path(var)), db)


def _number(value, kind):
    return kind(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def plan_item_rows(path):
    """One tuple per item of each day of a plan's JSON. `item_key` and `unit_count` are
    what the Workouts app keys and counts its buttons by."""
    path = Path(path)
    out = []
    for d in json.loads(path.read_text()).get("days", []):
        for i, item in enumerate(d.get("items") or []):
            out.append(
                (
                    d["date"],
                    i,
                    path.stem,
                    checks.item_key(item),
                    item.get("exercise") or item.get("text") or "",
                    item.get("exercise"),
                    _number(item.get("sets"), int),
                    _number(item.get("reps"), int),
                    _number(item.get("load_lb"), float),
                    checks.units(item),
                )
            )
    return out


def check_rows(path):
    """One tuple per line of checks.jsonl, numbered in the order they were tapped."""
    path = Path(path)
    out = []
    for i, line in enumerate(path.read_text().splitlines() if path.exists() else []):
        r = json.loads(line)
        out.append((i, datetime.fromisoformat(r["at"]), r["date"], r["item"], r["n"], r["done"]))
    return out


def _plan_files(paths, var):
    folder = Path(var or config.VAR) / "training" / "plans"
    return sorted(map(Path, paths)) if paths else sorted(folder.glob("*-W*.json"))


def _by_key(files, rows_of, width):
    """Rows from every file keyed by their first `width` fields: a date belongs to one
    ISO week, and a later file would win."""
    rows = {}
    for path in files:
        for r in rows_of(path):
            rows[r[:width]] = r
    return list(rows.values())


def ingest_plans(paths=None, var=None, db=None):
    """Reload raw.training_plan_days from the plan JSON files. Returns (files, rows)."""
    files = _plan_files(paths, var)
    return len(files), _replace("training_plan_days", _by_key(files, plan_rows, 1), db)


def ingest_plan_items(paths=None, var=None, db=None):
    """Reload raw.training_plan_items from the plan JSON files. Returns (files, rows)."""
    files = _plan_files(paths, var)
    return len(files), _replace("training_plan_items", _by_key(files, plan_item_rows, 2), db)


def ingest_checks(path=None, var=None, db=None):
    """Reload raw.training_checks from checks.jsonl. Returns the row count."""
    return _replace("training_checks", check_rows(path or checks.checks_path(var)), db)
