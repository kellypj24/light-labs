"""PJ's notes and the weekly plans landed in DuckDB, for the planned-versus-done marts.

`raw.training_notes`: one row per thing a note said (`training.notes`), every note kept,
voided ones flagged. `raw.training_plan_days`: one row per day of each plan in
var/training/plans/*.json, as it stood when last planned. Both are snapshot replaces of
small local files (`lab training ingest-notes`, `ingest-plans`; Dagster's
`raw/training_notes` and `raw/training_plan_days`).

The note text and each row's `what` are in the raw table and staging only. They stay out
of the marts the planner reads, so they never reach its Claude call.
"""

import json
from datetime import datetime
from pathlib import Path

from light_labs import config
from light_labs.evals import results
from light_labs.training import notes

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


def ingest_plans(paths=None, var=None, db=None):
    """Reload raw.training_plan_days from the plan JSON files. Returns (files, rows)."""
    folder = Path(var or config.VAR) / "training" / "plans"
    files = sorted(map(Path, paths)) if paths else sorted(folder.glob("*-W*.json"))
    rows = {}
    for path in files:  # a date belongs to one ISO week; a later file would win
        for r in plan_rows(path):
            rows[r[0]] = r
    return len(files), _replace("training_plan_days", list(rows.values()), db)
