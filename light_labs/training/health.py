"""Apple Health workouts landed in `raw.health_workouts`.

Strava writes rides and runs to Health; the Health Exporter & Shortcuts app's Export
Workouts action turns them into JSON, and a Shortcut sends it to Rush on Telegram, who
saves it as var/training/health/inbox/health-<date>-<time>.json. Each export covers a
window of days, so `ingest` upserts by the workout's HealthKit uuid: overlapping exports
never duplicate, and every drop is archived in var/training/health/.

Required keys are checked; statistics are kept whole (as JSON) beside the few columns
the marts use, so a new activity type or statistic needs no change here. Health records
the same run twice at times (the Watch and Strava) and keeps accidental starts; staging
flags those, the raw table keeps everything.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

from light_labs import config
from light_labs.evals import results

REQUIRED = ("uuid", "activityType", "startDate", "endDate", "duration", "source")
HK = "HKQuantityTypeIdentifier"
DISTANCE_KEYS = (
    "DistanceWalkingRunning",
    "DistanceCycling",
    "DistanceSwimming",
    "DistanceWheelchair",
    "DistanceDownhillSnowSports",
)

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE TABLE IF NOT EXISTS raw.health_workouts (
    workout_uuid VARCHAR PRIMARY KEY,
    activity_type VARCHAR NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL,
    duration_seconds DOUBLE NOT NULL,
    is_indoor BOOLEAN,
    source VARCHAR NOT NULL,
    distance_m DOUBLE,
    energy_kcal DOUBLE,
    heart_rate_avg DOUBLE,
    heart_rate_max DOUBLE,
    event_count INTEGER,
    statistics JSON,
    exported_at TIMESTAMPTZ,
    source_file VARCHAR NOT NULL
);
"""
COLUMNS = [
    "workout_uuid",
    "activity_type",
    "started_at",
    "ended_at",
    "duration_seconds",
    "is_indoor",
    "source",
    "distance_m",
    "energy_kcal",
    "heart_rate_avg",
    "heart_rate_max",
    "event_count",
    "statistics",
    "exported_at",
    "source_file",
]


class NotHealth(ValueError):
    """The JSON isn't a workouts export this parser knows."""


def home(var=None):
    return Path(var or config.VAR) / "training" / "health"


def inbox(var=None):
    return home(var) / "inbox"


def _at(text):
    return datetime.fromisoformat(text)


def _stat(stats, key, field):
    value = (stats.get(HK + key) or {}).get(field)
    return float(value) if value is not None else None


def _distance(stats):
    """Metres, from whichever distance statistic the workout has."""
    for key in DISTANCE_KEYS:
        stat = stats.get(HK + key) or {}
        if stat.get("sum") is not None:
            unit, value = stat.get("unit", "m"), float(stat["sum"])
            factor = {"m": 1, "km": 1000, "mi": 1609.344, "yd": 0.9144, "ft": 0.3048}
            if unit not in factor:
                raise NotHealth(f"unknown distance unit {unit!r}")
            return value * factor[unit]
    return None


def parse(data):
    """Bytes or text of one export → (exported_at or None, list of workout dicts)."""
    if isinstance(data, bytes):
        data = data.decode("utf-8-sig")
    try:
        body = json.loads(data)
    except json.JSONDecodeError as e:
        raise NotHealth(f"not JSON: {e}") from None
    if not isinstance(body, dict) or not isinstance(body.get("workouts"), list):
        raise NotHealth("no `workouts` list")
    info = body.get("exportInfo") or {}
    exported = _at(info["exportDate"]) if info.get("exportDate") else None
    workouts = []
    for i, w in enumerate(body["workouts"]):
        missing = [k for k in REQUIRED if w.get(k) in (None, "")]
        if missing:
            raise NotHealth(f"workout {i}: missing {missing}")
        stats = w.get("statistics") or {}
        try:
            workouts.append(
                {
                    "workout_uuid": w["uuid"],
                    "activity_type": w["activityType"],
                    "started_at": _at(w["startDate"]),
                    "ended_at": _at(w["endDate"]),
                    "duration_seconds": float(w["duration"]),
                    "is_indoor": w.get("indoor"),
                    "source": w["source"],
                    "distance_m": _distance(stats),
                    "energy_kcal": _stat(stats, "ActiveEnergyBurned", "sum"),
                    "heart_rate_avg": _stat(stats, "HeartRate", "average"),
                    "heart_rate_max": _stat(stats, "HeartRate", "max"),
                    "event_count": len(w.get("events") or []),
                    "statistics": json.dumps(stats, sort_keys=True),
                }
            )
        except NotHealth:
            raise
        except (TypeError, ValueError) as e:
            raise NotHealth(f"workout {i}: {e}") from None
    return exported, workouts


def summary(workouts):
    """'11 workouts (running), 2026-10-13 to 2026-11-05', for Rush's reply."""
    if not workouts:
        return "0 workouts"
    days = sorted(w["started_at"].date() for w in workouts)
    kinds = ", ".join(sorted({w["activity_type"] for w in workouts}))
    return f"{len(workouts)} workouts ({kinds}), {days[0]} to {days[-1]}"


def collect(var=None):
    """Move inbox drops to var/training/health/. Returns the moved paths."""
    moved = []
    box = inbox(var)
    for path in sorted(box.glob("*.json")) if box.exists() else []:
        dest = home(var) / path.name
        shutil.move(path, dest)
        moved.append(dest)
    return moved


def ingest(paths=None, var=None, db=None):
    """Upsert workouts from `paths` (copied into var/training/health/ first) or from the
    inbox's drops. Returns (files loaded, workouts upserted, table total)."""
    home(var).mkdir(parents=True, exist_ok=True)
    if paths:
        files = []
        for p in map(Path, paths):
            if p.resolve().parent != home(var).resolve():
                shutil.copy2(p, home(var) / p.name)
            files.append(home(var) / p.name)
    else:
        files = collect(var)
    rows = {}
    for path in sorted(files):  # later drops win on the same uuid
        exported, workouts = parse(path.read_bytes())
        for w in workouts:
            row = {**w, "exported_at": exported, "source_file": str(path)}
            rows[w["workout_uuid"]] = tuple(row[c] for c in COLUMNS)
    with results.connect(db) as con:
        con.execute(SCHEMA)
        con.execute("BEGIN")
        if rows:
            marks = ", ".join("?" for _ in COLUMNS)
            cols = ", ".join(COLUMNS)
            con.executemany(
                f"INSERT OR REPLACE INTO raw.health_workouts ({cols}) VALUES ({marks})",
                list(rows.values()),
            )
        con.execute("COMMIT")
        total = con.execute("SELECT count(*) FROM raw.health_workouts").fetchone()[0]
    return len(files), len(rows), total
