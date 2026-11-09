"""Strong's CSV export landed in `raw.strong_sets`.

PJ shares the export to Rush on Telegram; Rush saves it as
var/training/strong/inbox/strong-<yyyy-mm-dd>.csv. `ingest` moves inbox files to
var/training/strong/ and reloads the table from the newest one: every export holds the
full history, so each load is a snapshot replace and a skipped week costs nothing.

Strong's layout differs across versions and platforms, so the header is pinned and
anything else is refused rather than guessed at. Rest-timer rows are not sets and are
dropped. A letter in Set Order (W warm-up, D drop, F failure) replaces the set's number,
so sets are numbered by position within their exercise. The export has no unit column:
weights are in UNIT.
"""

import csv
import hashlib
import io
import re
import shutil
from datetime import date, datetime
from pathlib import Path

from light_labs import config
from light_labs.evals import results

HEADER = [
    "Date",
    "Workout Name",
    "Duration",
    "Exercise Name",
    "Set Order",
    "Weight",
    "Reps",
    "Distance",
    "Seconds",
    "Notes",
    "Workout Notes",
    "RPE",
]
UNIT = "lb"
SET_TYPES = {"W": "warmup", "D": "drop", "F": "failure"}
REST = "Rest Timer"
NAME = re.compile(r"^strong-(\d{4}-\d{2}-\d{2})\.csv$")
_DURATION = re.compile(r"^(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?$")

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE TABLE IF NOT EXISTS raw.strong_sets (
    set_id VARCHAR NOT NULL,
    workout_at TIMESTAMP NOT NULL,
    workout_name VARCHAR NOT NULL,
    duration_minutes INTEGER,
    exercise VARCHAR NOT NULL,
    set_number INTEGER NOT NULL,
    set_type VARCHAR NOT NULL,
    weight DOUBLE,
    unit VARCHAR NOT NULL,
    reps DOUBLE,
    distance DOUBLE,
    seconds DOUBLE,
    rpe DOUBLE,
    notes VARCHAR,
    workout_notes VARCHAR,
    exported_on DATE NOT NULL,
    source_file VARCHAR NOT NULL
);
"""
COLUMNS = [
    "set_id",
    "workout_at",
    "workout_name",
    "duration_minutes",
    "exercise",
    "set_number",
    "set_type",
    "weight",
    "unit",
    "reps",
    "distance",
    "seconds",
    "rpe",
    "notes",
    "workout_notes",
    "exported_on",
    "source_file",
]


class NotStrong(ValueError):
    """The file isn't a Strong export this parser knows."""


def home(var=None):
    return Path(var or config.VAR) / "training" / "strong"


def inbox(var=None):
    return home(var) / "inbox"


def _minutes(text):
    m = _DURATION.match(text.strip())
    if not text.strip() or not m or not any(m.groups()):
        raise NotStrong(f"unreadable Duration {text!r}")
    h, mins, s = (int(g or 0) for g in m.groups())
    return h * 60 + mins + round(s / 60)


def _num(text):
    return float(text) if text.strip() else None


def parse(data):
    """Bytes or text of one export → list of set dicts (rest timers dropped)."""
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data.lstrip("﻿")
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header != HEADER:
        extra = sorted(set(header or []) - set(HEADER))
        missing = [c for c in HEADER if c not in (header or [])]
        raise NotStrong(f"header differs (unknown {extra}, missing {missing})")
    sets, position = [], {}
    for line, row in enumerate(reader, start=2):
        if len(row) != len(HEADER):
            raise NotStrong(f"line {line}: {len(row)} fields, expected {len(HEADER)}")
        r = dict(zip(HEADER, row, strict=True))
        order = r["Set Order"].strip()
        if order == REST:
            continue
        if order.isdigit():
            set_type = "normal"
        elif order in SET_TYPES:
            set_type = SET_TYPES[order]
        else:
            raise NotStrong(f"line {line}: unknown Set Order {order!r}")
        try:
            at = datetime.strptime(r["Date"], "%Y-%m-%d %H:%M:%S")
        except ValueError as e:
            raise NotStrong(f"line {line}: {e}") from None
        key = (r["Date"], r["Workout Name"], r["Exercise Name"])
        position[key] = position.get(key, 0) + 1
        set_id = hashlib.sha256("|".join([*key, str(position[key])]).encode()).hexdigest()[:16]
        try:
            sets.append(
                {
                    "set_id": set_id,
                    "workout_at": at,
                    "workout_name": r["Workout Name"],
                    "duration_minutes": _minutes(r["Duration"]),
                    "exercise": r["Exercise Name"],
                    "set_number": position[key],
                    "set_type": set_type,
                    "weight": _num(r["Weight"]),
                    "unit": UNIT,
                    "reps": _num(r["Reps"]),
                    "distance": _num(r["Distance"]),
                    "seconds": _num(r["Seconds"]),
                    "rpe": _num(r["RPE"]),
                    "notes": r["Notes"] or None,
                    "workout_notes": r["Workout Notes"] or None,
                }
            )
        except ValueError as e:
            raise NotStrong(f"line {line}: {e}") from None
    return sets


def summary(sets):
    """'4587 sets, 2021-08-30 to 2026-11-04', for Rush's reply."""
    if not sets:
        return "0 sets"
    days = sorted(s["workout_at"].date() for s in sets)
    return f"{len(sets)} sets, {days[0]} to {days[-1]}"


def _exported_on(path):
    m = NAME.match(path.name)
    return date.fromisoformat(m.group(1)) if m else date.fromtimestamp(path.stat().st_mtime)


def collect(var=None):
    """Move inbox drops to var/training/strong/ (same name replaces). Returns moved names."""
    moved = []
    box = inbox(var)
    for path in sorted(box.glob("*.csv")) if box.exists() else []:
        shutil.move(path, home(var) / path.name)
        moved.append(path.name)
    return moved


def newest(var=None):
    files = sorted(home(var).glob("*.csv"), key=lambda p: (_exported_on(p), p.stat().st_mtime))
    return files[-1] if files else None


def ingest(path=None, var=None, db=None):
    """Reload raw.strong_sets from `path` (copied into var/training/strong/ first) or the
    newest export there after collecting the inbox. Returns (file or None, sets)."""
    home(var).mkdir(parents=True, exist_ok=True)
    if path:
        path = Path(path)
        if path.resolve().parent != home(var).resolve():
            shutil.copy2(path, home(var) / path.name)
        path = home(var) / path.name
    else:
        collect(var)
        path = newest(var)
    sets = parse(path.read_bytes()) if path else []
    exported_on = _exported_on(path) if path else None
    rows = [
        tuple({**s, "exported_on": exported_on, "source_file": str(path)}[c] for c in COLUMNS)
        for s in sets
    ]
    with results.connect(db) as con:
        con.execute(SCHEMA)
        con.execute("BEGIN")
        con.execute("DELETE FROM raw.strong_sets")
        if rows:
            marks = ", ".join("?" for _ in COLUMNS)
            cols = ", ".join(COLUMNS)
            con.executemany(f"INSERT INTO raw.strong_sets ({cols}) VALUES ({marks})", rows)
        con.execute("COMMIT")
    return path, len(rows)
