"""Sensors: rebuild the analytics when a fight ends, a queue changes, a Strong export or
Health workouts drop lands or PJ's training notes or plans change, and Claude Code's usage
once a day.

All are on by default and tick in the Dagster daemon (`just dagster-install`). They only
launch the landing + dbt jobs, never a fight, and skip while a fight is on or any heavy job
holds ~/.cache/light-labs/heavy.lock (one heavy job at a time on the laptop). Turning one
off in the UI persists in var/dagster.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dagster import DefaultSensorStatus, RunRequest, SensorEvaluationContext, SkipReason, sensor

from light_labs import config
from light_labs.core.heavy import holder
from light_labs.evals.fights import live_fight, run_records
from light_labs.orchestration.jobs import (
    claude_job,
    evals_job,
    health_job,
    queue_job,
    strong_job,
    training_record_job,
)

# `just eval` loads its own results when a fight ends; let that finish first.
SETTLE = timedelta(minutes=2)


def finished_since(evals_dir, cursor, now=None):
    """(run_ids that ended after `cursor` and have settled, new cursor)."""
    now = now or datetime.now(UTC)
    after = datetime.fromisoformat(cursor) if cursor else None
    ended = []
    for _, record in run_records(evals_dir):
        if record.get("status") == "running" or not record.get("ended_at"):
            continue
        at = datetime.fromisoformat(record["ended_at"]).astimezone(UTC)
        if (after is None or at > after) and now - at >= SETTLE:
            ended.append((at, record["run_id"]))
    if not ended:
        return [], cursor
    ended.sort()
    return [run_id for _, run_id in ended], ended[-1][0].isoformat()


def queue_fingerprint(var_dir):
    """Changes whenever a queued draft is added, moved between buckets or edited."""
    h = hashlib.sha256()
    for path in sorted(Path(var_dir).glob("*/queue/*/*.json")):
        h.update(f"{path.relative_to(var_dir)}:{path.stat().st_mtime_ns}\n".encode())
    return h.hexdigest()[:16]


@sensor(
    job=evals_job,
    minimum_interval_seconds=60,
    default_status=DefaultSensorStatus.RUNNING,
    description="Rebuilds the eval marts after a fight ends (completed or cancelled).",
)
def fight_finished(context: SensorEvaluationContext):
    evals_dir = config.VAR / "evals"
    if run_id := live_fight(evals_dir):
        return SkipReason(f"fight {run_id} is running")
    if held := holder():
        return SkipReason(f"heavy job {held['job']} is running")
    if context.cursor is None:
        # First tick: start from now rather than replaying every old fight.
        context.update_cursor(datetime.now(UTC).isoformat())
        return SkipReason("cursor initialised")
    run_ids, cursor = finished_since(evals_dir, context.cursor)
    if not run_ids:
        return SkipReason("no fight has ended since the last build")
    context.update_cursor(cursor)
    return RunRequest(run_key=f"fights:{cursor}", tags={"lab/runs": ",".join(run_ids)[:200]})


@sensor(
    job=queue_job,
    minimum_interval_seconds=300,
    default_status=DefaultSensorStatus.RUNNING,
    description="Rebuilds the queue marts when a robot's approval queue changes.",
)
def queue_changed(context: SensorEvaluationContext):
    if run_id := live_fight(config.VAR / "evals"):
        return SkipReason(f"fight {run_id} is running")
    if held := holder():
        return SkipReason(f"heavy job {held['job']} is running")
    fingerprint = queue_fingerprint(config.VAR)
    if fingerprint == context.cursor:
        return SkipReason("queues unchanged")
    context.update_cursor(fingerprint)
    return RunRequest(run_key=f"queues:{fingerprint}")


def drop_fingerprint(var_dir, kind="strong"):
    """The drops waiting in var/training/<kind>/inbox/, or None when it's empty. Ingest
    moves them out, so an emptied inbox never asks for a run."""
    box = Path(var_dir) / "training" / kind / "inbox"
    paths = (
        sorted(p for p in box.iterdir() if p.suffix in (".csv", ".json")) if box.exists() else []
    )
    if not paths:
        return None
    h = hashlib.sha256()
    for path in paths:
        st = path.stat()
        h.update(f"{path.name}:{st.st_mtime_ns}:{st.st_size}\n".encode())
    return h.hexdigest()[:16]


@sensor(
    job=strong_job,
    minimum_interval_seconds=60,
    default_status=DefaultSensorStatus.RUNNING,
    description="Lands a Strong export when Rush drops one in var/training/strong/inbox/.",
)
def strong_dropped(context: SensorEvaluationContext):
    if run_id := live_fight(config.VAR / "evals"):
        return SkipReason(f"fight {run_id} is running")
    if held := holder():
        return SkipReason(f"heavy job {held['job']} is running")
    fingerprint = drop_fingerprint(config.VAR)
    if fingerprint is None:
        return SkipReason("inbox empty")
    if fingerprint == context.cursor:
        return SkipReason("drop already requested")
    context.update_cursor(fingerprint)
    return RunRequest(run_key=f"strong:{fingerprint}")


@sensor(
    job=health_job,
    minimum_interval_seconds=60,
    default_status=DefaultSensorStatus.RUNNING,
    description="Upserts Health workouts when Rush drops an export in var/training/health/inbox/.",
)
def health_dropped(context: SensorEvaluationContext):
    if run_id := live_fight(config.VAR / "evals"):
        return SkipReason(f"fight {run_id} is running")
    if held := holder():
        return SkipReason(f"heavy job {held['job']} is running")
    fingerprint = drop_fingerprint(config.VAR, "health")
    if fingerprint is None:
        return SkipReason("inbox empty")
    if fingerprint == context.cursor:
        return SkipReason("drop already requested")
    context.update_cursor(fingerprint)
    return RunRequest(run_key=f"health:{fingerprint}")


def record_fingerprint(var_dir, now=None):
    """Changes with PJ's notes and the plans' JSON; None while the newest change is
    younger than SETTLE. A note is often followed by a replan within a minute, and the
    planner reads var/lab.duckdb for it: a run that starts in between holds the write
    lock the planner then waits on."""
    home = Path(var_dir) / "training"
    paths = sorted([*home.glob("notes/notes.jsonl"), *home.glob("plans/*-W*.json")])
    if not paths:
        return None
    now = now or datetime.now(UTC)
    h, newest = hashlib.sha256(), 0
    for path in paths:
        st = path.stat()
        newest = max(newest, st.st_mtime)
        h.update(f"{path.relative_to(home)}:{st.st_mtime_ns}:{st.st_size}\n".encode())
    if now.timestamp() - newest < SETTLE.total_seconds():
        return None
    return h.hexdigest()[:16]


@sensor(
    job=training_record_job,
    minimum_interval_seconds=300,
    default_status=DefaultSensorStatus.RUNNING,
    description="Reloads PJ's training notes and plans once they have been still for two minutes.",
)
def training_record_changed(context: SensorEvaluationContext):
    if run_id := live_fight(config.VAR / "evals"):
        return SkipReason(f"fight {run_id} is running")
    if held := holder():
        return SkipReason(f"heavy job {held['job']} is running")
    fingerprint = record_fingerprint(config.VAR)
    if fingerprint is None:
        return SkipReason("no notes or plans, or one changed in the last two minutes")
    if fingerprint == context.cursor:
        return SkipReason("notes and plans unchanged")
    context.update_cursor(fingerprint)
    return RunRequest(run_key=f"training-record:{fingerprint}")


def claude_due(cursor, now=None):
    """The UTC day to load Claude Code's usage for, or None when today's is done."""
    today = (now or datetime.now(UTC)).date().isoformat()
    return None if cursor == today else today


@sensor(
    job=claude_job,
    minimum_interval_seconds=3600,
    default_status=DefaultSensorStatus.RUNNING,
    description="Loads Claude Code's transcripts once a day, well inside "
    "Claude Code's 30-day transcript cleanup.",
)
def claude_daily(context: SensorEvaluationContext):
    if run_id := live_fight(config.VAR / "evals"):
        return SkipReason(f"fight {run_id} is running")
    if held := holder():
        return SkipReason(f"heavy job {held['job']} is running")
    if context.cursor is None:
        # First tick: start from now; `just analytics` loads everything on demand.
        context.update_cursor(datetime.now(UTC).date().isoformat())
        return SkipReason("cursor initialised")
    day = claude_due(context.cursor)
    if day is None:
        return SkipReason("already loaded today")
    context.update_cursor(day)
    return RunRequest(run_key=f"claude:{day}")


ALL_SENSORS = [
    fight_finished,
    queue_changed,
    claude_daily,
    strong_dropped,
    health_dropped,
    training_record_changed,
]
