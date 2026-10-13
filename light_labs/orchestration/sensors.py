"""Sensors: rebuild the analytics when a fight ends or a queue changes.

Both skip while a fight is on (one heavy job at a time on the laptop) and default to
STOPPED: turn them on in the UI once; the state persists in var/dagster.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dagster import DefaultSensorStatus, RunRequest, SensorEvaluationContext, SkipReason, sensor

from light_labs import config
from light_labs.orchestration.jobs import evals_job, queue_job

# A fight is live while its record says running and it wrote telemetry this recently
# (the runner reads every 30s; a killed runner leaves a stale "running" record).
LIVE_WITHIN = timedelta(minutes=2)
# `just eval` loads its own results when a fight ends; let that finish first.
SETTLE = timedelta(minutes=2)


def _records(evals_dir):
    out = []
    for path in Path(evals_dir).glob("*.run.json"):
        try:
            out.append((path, json.loads(path.read_text())))
        except (OSError, json.JSONDecodeError):
            continue  # mid-write or unreadable: next tick
    return out


def live_fight(evals_dir, now=None):
    """run_id of a fight in progress, or None."""
    now = now or datetime.now(UTC)
    for path, record in _records(evals_dir):
        if record.get("status") != "running":
            continue
        telemetry = path.with_name(f"{record['run_id']}.telemetry.jsonl")
        seen = max(p.stat().st_mtime for p in (path, telemetry) if p.exists())
        if now - datetime.fromtimestamp(seen, UTC) < LIVE_WITHIN:
            return record["run_id"]
    return None


def finished_since(evals_dir, cursor, now=None):
    """(run_ids that ended after `cursor` and have settled, new cursor)."""
    now = now or datetime.now(UTC)
    after = datetime.fromisoformat(cursor) if cursor else None
    ended = []
    for _, record in _records(evals_dir):
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
    default_status=DefaultSensorStatus.STOPPED,
    description="Rebuilds the eval marts after a fight ends (completed or cancelled).",
)
def fight_finished(context: SensorEvaluationContext):
    evals_dir = config.VAR / "evals"
    if run_id := live_fight(evals_dir):
        return SkipReason(f"fight {run_id} is running")
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
    default_status=DefaultSensorStatus.STOPPED,
    description="Rebuilds the queue marts when a robot's approval queue changes.",
)
def queue_changed(context: SensorEvaluationContext):
    if run_id := live_fight(config.VAR / "evals"):
        return SkipReason(f"fight {run_id} is running")
    fingerprint = queue_fingerprint(config.VAR)
    if fingerprint == context.cursor:
        return SkipReason("queues unchanged")
    context.update_cursor(fingerprint)
    return RunRequest(run_key=f"queues:{fingerprint}")


ALL_SENSORS = [fight_finished, queue_changed]
