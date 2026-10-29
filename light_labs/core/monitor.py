"""What the lab is doing now: one snapshot for Rush's `/lab` page and `lab heavy watch`.

Reads what is already on disk: the heavy-job lock and its HISTORY, the running job's own
output files (in that job's var/, which a worktree has its own of), and Dagster's run
storage. Writes nothing.

The snapshot goes to a phone over the tailnet, so it carries counts and readings only:
never a command line, path, pid or anything read out of a record (the records hold mail).
Lock detail passes through DETAIL_KEYS; busy processes are reduced to their kind.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from light_labs import config
from light_labs.core import heavy

HISTORY_SHOWN = 5
DAGSTER_SHOWN = 5
DAGSTER_ACTIVE = ("QUEUED", "NOT_STARTED", "STARTING", "STARTED", "CANCELING")
DETAIL_KEYS = ("label", "sample")
HISTORY_TAIL_BYTES = 64 * 1024
HISTORY_KEYS = ("job", "started_at", "ended_at", "outcome")


def kinds(procs):
    """What sort of thing each busy process is, without its command line."""
    out = []
    for line in procs:
        if (kind := heavy.busy_kind(line)) not in out:
            out.append(kind)
    return out


def _since(iso, now):
    try:
        return (now - datetime.fromisoformat(iso)).total_seconds()
    except (AttributeError, ValueError):
        return None


def _lines(path):
    with path.open("rb") as f:
        return sum(1 for _ in f)


def _newest(paths, after):
    """The most recently modified of `paths` changed at or after `after` (epoch s)."""
    paths = [p for p in paths if p.stat().st_mtime >= after]
    return max(paths, key=lambda p: p.stat().st_mtime, default=None)


def progress(rec):
    """{"what", "done", "total"} for the lock holder's job, or None if it has no reader."""
    var = Path(rec.get("var") or config.VAR)
    started = datetime.fromisoformat(rec["started_at"]).timestamp()
    detail = rec.get("detail") or {}
    if rec["job"] == "roll-keep":
        f = _newest((var / "roll" / "keep").glob("shadow-*.jsonl"), started)
        done = _lines(f) if f else 0
        return {
            "what": detail.get("label", "shadow labels"),
            "done": done,
            "total": detail.get("total") or detail.get("sample"),
        }
    if rec["job"] == "fight":
        f = _newest((var / "evals").glob("*.run.json"), started)
        if not f:
            return None
        run = json.loads(f.read_text())
        return {
            "what": run.get("run_id", f.stem),
            "done": run.get("done"),
            "total": run.get("total"),
        }
    return None


def dagster_runs(db=None, limit=DAGSTER_SHOWN):
    """Active Dagster runs first, then the latest finished, from its run storage."""
    db = db or config.VAR / "dagster" / "history" / "runs.db"
    if not db.exists():
        return []
    marks = ",".join("?" * len(DAGSTER_ACTIVE))
    sql = (
        f"SELECT pipeline_name, status, start_time, end_time FROM runs "
        f"ORDER BY status IN ({marks}) DESC, id DESC LIMIT ?"
    )
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2) as con:
            rows = con.execute(sql, (*DAGSTER_ACTIVE, limit)).fetchall()
    except sqlite3.Error:
        return []
    return [
        {"job": j, "status": s, "start": a, "end": b, "active": s in DAGSTER_ACTIVE}
        for j, s, a, b in rows
    ]


def history(lock=None, limit=HISTORY_SHOWN):
    """The last `limit` finished heavy jobs, newest first."""
    try:
        with heavy.history_path(lock).open("rb") as f:
            f.seek(max(0, f.seek(0, 2) - HISTORY_TAIL_BYTES))
            lines = f.read().decode(errors="replace").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and all(isinstance(rec.get(k), str) for k in HISTORY_KEYS):
            out.append({k: rec[k] for k in HISTORY_KEYS})
        if len(out) == limit:
            break
    return out


def snapshot(lock=None, read=heavy.reading, procs=None, db=None):
    now = datetime.now(UTC)
    r = read()
    busy = kinds(heavy.busy_processes() if procs is None else procs)  # never the command line
    held = heavy.holder(lock)
    job = None
    if held:
        swap_start = held.get("swap_start")
        detail = held.get("detail") or {}
        job = {
            "job": held["job"],
            "started_at": held["started_at"],
            "elapsed_s": _since(held["started_at"], now),
            "detail": {k: detail[k] for k in DETAIL_KEYS if k in detail},
            "progress": progress(held),
            "swap_growth_mb": (
                r["swap_mb"] - swap_start if None not in (r["swap_mb"], swap_start) else None
            ),
        }
    why_not = (
        (f"{held['job']} holds the lock" if held else "") or heavy.too_busy(r, busy) or heavy.hot(r)
    )
    return {
        "at": now.isoformat(),
        "job": job,
        "machine": r,
        "limits": {"swap_growth_mb": heavy.SWAP_GROWTH_MB, "battery_c": heavy.BATTERY_MAX_C},
        "hot": heavy.hot(r),
        "critical": heavy.critical(r, (held or {}).get("swap_start")),
        "start_ok": not why_not,
        "why_not": why_not,
        "busy": busy,
        "dagster": dagster_runs(db),
        "history": history(lock),
    }


def duration(s):
    if s is None:
        return "?"
    s = int(s)
    return f"{s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m{s % 60:02d}s"


def text(snap):
    """The snapshot for a terminal."""
    m, j = snap["machine"], snap["job"]
    lines = []
    if j:
        p = j["progress"]
        prog = ""
        if p and p.get("total"):
            prog = f"  {p['what']}: {p['done']}/{p['total']} ({p['done'] / p['total']:.0%})"
        elif p:
            prog = f"  {p['what']}: {p['done']}"
        lines.append(f"job: {j['job']} {duration(j['elapsed_s'])}{prog}")
    else:
        lines.append("job: none")
    swap = j and j["swap_growth_mb"]
    lines.append(
        f"machine: thermal={m['thermal']} load={m['load_1']}/{m['cores']} "
        f"pressure={m['pressure']} swap={m['swap_mb']} MB"
        + (f" (+{swap:.0f} of {snap['limits']['swap_growth_mb']})" if swap is not None else "")
    )
    if snap["critical"] or snap["hot"]:
        lines.append(f"kill switch: {snap['critical'] or 'pause: ' + snap['hot']}")
    lines.append(f"start a heavy job: {'yes' if snap['start_ok'] else 'no, ' + snap['why_not']}")
    active = [d for d in snap["dagster"] if d["active"]]
    lines.append("dagster: " + (", ".join(f"{d['job']} {d['status']}" for d in active) or "idle"))
    for h in snap["history"]:
        took = _since(h["started_at"], datetime.fromisoformat(h["ended_at"]))
        lines.append(f"  {h['ended_at'][:16]}  {h['job']:<10} {duration(took):>7}  {h['outcome']}")
    return "\n".join(lines)
