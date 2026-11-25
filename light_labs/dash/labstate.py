"""The lab's own state for the dashboard: what the robots are holding for PJ, whether the
scheduled jobs are healthy, today's training session and the latest eval per stage.

Everything here reads files and local process tables. Nothing is written and nothing
calls the network.
"""

import json
import os
import plistlib
import sqlite3
import subprocess
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from light_labs import config
from light_labs.core import heavy, mcp_server
from light_labs.training.calendar import TZ

LABEL_PREFIX = "com.pjkelly."
AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
# launchd reports a job it stopped itself (a redeploy's restart) as killed by SIGTERM.
STOPPED_BY_LAUNCHD = {0, -15, 143}
RUSH_STALE = timedelta(minutes=90)  # Rush ticks hourly
HEARTBEAT_STALE = timedelta(minutes=5)
HEARTBEATS = ("SCHEDULER", "SENSOR")


def _aware(stamp):
    at = datetime.fromisoformat(stamp)
    return at if at.tzinfo else at.replace(tzinfo=UTC)


# --- what the robots hold for PJ


def queue(now, pending=None, asks_path=None):
    """One row per robot and draft kind, oldest first, plus Rush's held asks."""
    items = mcp_server.queue_pending() if pending is None else pending
    groups = {}
    for i in items:
        robot, kind = str(i.get("robot") or "?"), str(i.get("kind") or "?")
        g = groups.setdefault(
            (robot, kind),
            {"robot": robot, "kind": kind, "count": 0, "escalated": 0, "oldest": None},
        )
        g["count"] += 1
        g["escalated"] += bool(i.get("escalated"))
        try:
            created = _aware(i["created"])
        except (KeyError, TypeError, ValueError):
            continue
        if g["oldest"] is None or created < g["oldest"]:
            g["oldest"] = created
    rows = sorted(groups.values(), key=lambda g: g["oldest"] or now)
    held = held_asks(asks_path)
    if held:
        rows.append({"robot": "rush", "kind": "held ask", "count": held, "escalated": 0,
                     "oldest": None})  # fmt: skip
    return rows


def held_asks(path=None):
    """Asks whose latest record is `held`."""
    path = path or config.VAR / "rush" / "asks.jsonl"
    latest = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return 0
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("id"):
            latest[rec["id"]] = rec.get("outcome")
    return sum(outcome == "held" for outcome in latest.values())


# --- scheduled jobs


def launchctl_list(run=subprocess.run):
    """{label: (pid or None, last exit status or None)} for PJ's jobs; None if launchctl
    can't be asked."""
    try:
        out = run(["launchctl", "list"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    jobs = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or not parts[2].startswith(LABEL_PREFIX):
            continue
        pid = int(parts[0]) if parts[0].isdigit() else None
        try:
            status = int(parts[1])
        except ValueError:
            status = None
        jobs[parts[2]] = (pid, status)
    return jobs


def installed(agents_dir=None):
    """{label: keeps running} for PJ's plists in ~/Library/LaunchAgents."""
    out = {}
    for path in sorted((agents_dir or AGENTS_DIR).glob(f"{LABEL_PREFIX}*.plist")):
        try:
            job = plistlib.loads(path.read_bytes())
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
        out[job.get("Label", path.stem)] = bool(job.get("KeepAlive"))
    return out


def agents(loaded=None, plists=None):
    """One row per launchd job: {"name", "state", "ok"}."""
    loaded = launchctl_list() if loaded is None else loaded
    plists = installed() if plists is None else plists
    if loaded is None:
        return [{"name": "launchd", "state": "launchctl did not answer", "ok": False}]
    rows = []
    for label in sorted(set(loaded) | set(plists)):
        name = label.removeprefix(LABEL_PREFIX).removeprefix("light-labs.")
        if label not in loaded:
            rows.append({"name": name, "state": "not loaded", "ok": False})
            continue
        pid, status = loaded[label]
        if pid is not None:
            rows.append({"name": name, "state": "running", "ok": True})
        elif plists.get(label):
            rows.append({"name": name, "state": "stopped", "ok": False})
        elif status in STOPPED_BY_LAUNCHD:
            rows.append({"name": name, "state": "ok", "ok": True})
        else:
            rows.append({"name": name, "state": f"last run failed (exit {status})", "ok": False})
    return rows


def _dagster_db(db=None):
    return db or config.VAR / "dagster" / "history" / "runs.db"


def _read_only(db):
    """A connection that writes nothing. A read-only open of a WAL database creates its
    -wal and -shm files when they are absent; with no WAL there is nothing in one to
    miss, so the file is opened immutable instead."""
    wal = db.with_name(db.name + "-wal").exists()
    return sqlite3.connect(f"file:{db}?mode=ro{'' if wal else '&immutable=1'}", uri=True, timeout=2)


def dagster_jobs(db=None):
    """The latest run of each Dagster job: {"name", "status", "at", "ok"}; [] without a
    readable run store."""
    db = _dagster_db(db)
    if not db.exists():
        return []
    sql = (
        "SELECT pipeline_name, status, COALESCE(end_time, start_time) FROM runs "
        "WHERE id IN (SELECT MAX(id) FROM runs GROUP BY pipeline_name) ORDER BY pipeline_name"
    )
    try:
        with closing(_read_only(db)) as con:
            found = con.execute(sql).fetchall()
    except sqlite3.Error:
        return []
    rows = []
    for name, status, at in found:
        when = datetime.fromtimestamp(at, UTC) if isinstance(at, (int, float)) else None
        rows.append(
            {"name": name, "status": status, "at": when,
             "ok": status not in ("FAILURE", "CANCELED")}
        )  # fmt: skip
    return rows


def dagster_heartbeat(now, db=None):
    """A problem line when the daemon's scheduler or sensor loop has stopped beating."""
    db = _dagster_db(db)
    if not db.exists():
        return None
    try:
        with closing(_read_only(db)) as con:
            beats = dict(con.execute("SELECT daemon_type, timestamp FROM daemon_heartbeats"))
    except sqlite3.Error:
        return None
    for kind in HEARTBEATS:
        if kind not in beats:
            return f"Dagster daemon: no {kind.lower()} heartbeat"
        try:
            last = _aware(str(beats[kind]))
        except ValueError:
            continue
        if now - last > HEARTBEAT_STALE:
            return (
                f"Dagster daemon: no {kind.lower()} heartbeat since {last.astimezone(TZ):%a %H:%M}"
            )
    return None


def rush_tick(now, state_path=None):
    """A problem line when Rush hasn't ticked for RUSH_STALE."""
    path = state_path or config.VAR / "rush" / "state.json"
    try:
        last = _aware(json.loads(path.read_text())["updated_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if now - last > RUSH_STALE:
        return f"Rush: no tick since {last.astimezone(TZ):%a %H:%M}"
    return None


def heavy_job(now, lock=None):
    """The heavy-lock holder as a line, or None. Reads the lock itself: heavy.holder()
    removes a dead holder's lock, and the dashboard writes nothing."""
    try:
        held = json.loads((lock or heavy.LOCK).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(held, dict) or not _alive(held.get("pid")):
        return None
    try:
        minutes = int((now - _aware(held["started_at"])).total_seconds() // 60)
    except (KeyError, TypeError, ValueError):
        return f"heavy job: {held.get('job', '?')}"
    return f"heavy job: {held.get('job', '?')}, {minutes}m"


def _alive(pid):
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def problems(now, agent_rows, job_rows, extra=()):
    """The top line: things that fail without telling anyone."""
    out = [f"{a['name']}: {a['state']}" for a in agent_rows if not a["ok"]]
    out += [f"{j['name']}: {j['status'].lower()}" for j in job_rows if not j["ok"]]
    out += [p for p in (dagster_heartbeat(now), rush_tick(now)) if p]
    return out + [p for p in extra if p]


# --- training and evals


def training_today(day, var=None):
    """Today's session from the stored plan, or None when no plan covers the day."""
    plans = (var or config.VAR) / "training" / "plans"
    for path in sorted(plans.glob("*.json"), reverse=True):
        try:
            days = json.loads(path.read_text()).get("days") or []
        except (OSError, ValueError, AttributeError):
            continue
        for d in days:
            if isinstance(d, dict) and d.get("date") == day.isoformat():
                slot = d.get("slot") or []
                return {
                    "rest": bool(d.get("rest")),
                    "title": str(d.get("title") or d.get("type") or ""),
                    "type": str(d.get("type") or ""),
                    "slot": "-".join(str(s) for s in slot) if len(slot) == 2 else "",
                    "items": len(d.get("items") or []),
                }
    return None


def evals(var=None):
    """The latest run of each eval stage, newest first."""
    latest = {}
    for path in ((var or config.VAR) / "evals").glob("*.run.json"):
        try:
            run = json.loads(path.read_text())
            started = _aware(run["started_at"].replace("Z", "+00:00"))
            stage = run["stage"]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        if stage not in latest or started > latest[stage]["at"]:
            latest[stage] = {
                "stage": stage,
                "at": started,
                "status": run.get("status") or "?",
                "passed": run.get("passed"),
                "done": run.get("done"),
                "total": run.get("total"),
            }
    return sorted(latest.values(), key=lambda r: r["at"], reverse=True)
