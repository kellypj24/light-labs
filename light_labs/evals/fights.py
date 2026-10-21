"""Whether a fight has the laptop. Dagster-free, so the slim `lab` install can ask too."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

# A fight is live while its record says running and it wrote telemetry this recently
# (the runner reads every 30s; a killed runner leaves a stale "running" record).
LIVE_WITHIN = timedelta(minutes=2)


def run_records(evals_dir):
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
    for path, record in run_records(evals_dir):
        if record.get("status") != "running":
            continue
        telemetry = path.with_name(f"{record['run_id']}.telemetry.jsonl")
        seen = max(p.stat().st_mtime for p in (path, telemetry) if p.exists())
        if now - datetime.fromtimestamp(seen, UTC) < LIVE_WITHIN:
            return record["run_id"]
    return None
