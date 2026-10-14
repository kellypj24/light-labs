"""Follow fights from a second terminal: `lab evals watch [run_id]`.

With no run_id it follows: the latest fight, then whichever fight starts next, until
Ctrl-C, so one terminal can stay on it all day. With a run_id it shows that run and exits
when it ends.

Reads what the Go runner writes as it goes: the run record (<run_id>.run.json), the
samples (<run_id>.jsonl, one line per finished sample) and the telemetry
(<run_id>.telemetry.jsonl). Read-only; it never touches the fight.
"""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from light_labs.evals.results import RESULTS


def latest_record(directory=RESULTS):
    records = sorted(Path(directory).glob("*.run.json"), key=lambda p: p.stat().st_mtime)
    return records[-1] if records else None


def _lines(path):
    if not path:
        return []
    try:
        return [json.loads(line) for line in Path(path).read_text().splitlines() if line]
    except (OSError, json.JSONDecodeError):
        return []


def _clock(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def render(record, samples, telemetry, now=None):
    """The watch screen as text."""
    now = now or datetime.now(UTC)
    started = datetime.fromisoformat(record["started_at"])
    ended = record.get("ended_at")
    elapsed = ((datetime.fromisoformat(ended) if ended else now) - started).total_seconds()
    done, total = record.get("done", 0), record.get("total", 0)
    left = elapsed / done * (total - done) if done else 0
    lines = [
        f"{record['run_id']}  {record['status'].upper()}"
        + (f" ({record['reason']})" if record.get("reason") else ""),
        f"stage {record['stage']}  {done}/{total} samples  {_clock(elapsed)} elapsed"
        + (f", ~{_clock(left)} left" if record["status"] == "running" and done else ""),
        "",
    ]
    by = {}
    for s in samples:
        b = by.setdefault(s["contestant"], {"passed": 0, "done": 0, "fixtures": {}})
        b["done"] += 1
        b["passed"] += s["passed"]
        b["fixtures"].setdefault(s["fixture"], []).append(s["passed"])
    for name in record.get("contestants", []):
        b = by.get(name)
        if not b:
            lines.append(f"  {name:12} waiting")
            continue
        clean = sum(all(v) for v in b["fixtures"].values())
        lines.append(
            f"  {name:12} {b['passed']}/{b['done']} samples ({100 * b['passed'] // b['done']}%)"
            f"  {clean}/{len(b['fixtures'])} fixtures clean so far"
        )
    fails = [s for s in samples if not s["passed"]][-5:]
    if fails:
        lines += ["", "  recent failures:"]
        for s in fails:
            why = next((c["name"] for c in s["checks"] if not c["passed"]), "?")
            lines.append(f"    {s['contestant']} {s['fixture']} #{s['sample']}: {why}")
    if telemetry:
        t = telemetry[-1]
        temps = [x["battery_temp_c"] for x in telemetry if x.get("battery_temp_c") is not None]
        parts = []
        if t.get("battery_temp_c") is not None:
            parts.append(f"battery {t['battery_temp_c']:.1f}°C (peak {max(temps):.1f})")
        if t.get("cpu_speed_limit") is not None and t["cpu_speed_limit"] < 100:
            parts.append(f"THROTTLED to {t['cpu_speed_limit']}%")
        if t.get("ollama_cpu") is not None:
            parts.append(f"ollama {t['ollama_cpu']:.0f}% cpu")
        if t.get("on_ac") is not None:
            power = "on AC" if t["on_ac"] else f"ON BATTERY {t.get('battery_pct', '?')}%"
            parts.append(power)
        if record.get("cool_pauses"):
            parts.append(f"cooled {record['cool_pauses']}x ({_clock(record['cool_seconds'])})")
        lines += ["", "  " + " | ".join(parts)]
    return "\n".join(lines)


def _screen(path):
    record = json.loads(path.read_text())
    screen = render(
        record,
        _lines(record.get("samples_file", "")),
        _lines(record.get("telemetry_file", "")),
    )
    return record, screen


def watch(run_id=None, directory=RESULTS, every=2.0, out=sys.stdout, sleep=time.sleep):
    """Redraw every `every` seconds. Returns the last record shown."""
    follow = run_id is None
    path = Path(directory) / f"{run_id}.run.json" if run_id else latest_record(directory)
    if not follow and not path.exists():
        sys.exit(f"no run {run_id} in {directory}")
    tty = out.isatty()
    record = None
    try:
        while True:
            if follow:
                path = latest_record(directory) or path
            if path is None:
                screen = "no fights yet; waiting for the first (Ctrl-C to quit)"
            else:
                try:
                    record, screen = _screen(path)
                except (OSError, json.JSONDecodeError):
                    sleep(every)  # the runner is replacing the file: next tick
                    continue
                if record["status"] != "running":
                    if not follow:
                        out.write(("\033[H\033[J" if tty else "\n") + screen + "\n")
                        return record
                    screen += "\n\nwaiting for the next fight (Ctrl-C to quit)"
            out.write(("\033[H\033[J" if tty else "\n") + screen + "\n")
            out.flush()
            sleep(every)
    except KeyboardInterrupt:
        out.write("\n")
        return record
