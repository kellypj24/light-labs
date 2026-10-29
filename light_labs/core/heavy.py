"""One heavy job at a time on PJ's laptop, and kill switches before it overheats.

A heavy job (a fight, `lab roll keep`, `just check`) holds LOCK. Before taking it,
`too_busy` refuses a busy machine: high load, memory pressure, a serious thermal state, a
container VM, a Dagster run. While it runs, `Guard.check` between units of work pauses
while the machine is hot (serious thermal state, CPU throttled, battery over 40°C, warn
memory pressure) and stops the job after MAX_WAIT; a watchdog thread stops it on critical
thermal state or memory pressure, or swap growth. A stop unloads the local models.
Dagster's sensors skip while the lock is held. Each finished job appends a line to
HISTORY, next to the lock; `light_labs.core.monitor` reads both for `/lab`.

`lab heavy run <job> -- <cmd>` wraps a command; Python jobs use `with job(...) as guard`.
Off in CI (`CI` set): GitHub's runners have none of these readings.
"""

import json
import os
import re
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from light_labs import config

# Machine-wide, not per checkout: worktrees each have their own var/.
LOCK = Path(os.environ.get("LAB_HEAVY_LOCK", Path.home() / ".cache" / "light-labs" / "heavy.lock"))
HISTORY_NAME = "history.jsonl"

BATTERY_MAX_C = 40.0
SWAP_GROWTH_MB = 2048
MAX_WAIT = 600
WATCH_EVERY = 15
PAUSE_STEP = 30

# NSProcessInfo.thermalState: the battery stopped reporting Temperature in late 2026
THERMAL = {0: "nominal", 1: "fair", 2: "serious", 3: "critical"}
THERMAL_JS = 'ObjC.import("Foundation"); $.NSProcessInfo.processInfo.thermalState'
# kern.memorystatus_vm_pressure_level
PRESSURE = {1: "normal", 2: "warn", 4: "critical"}
BUSY = re.compile(r"com\.apple\.Virtualization\.VirtualMachine|qemu-system|dagster api execute_run|dbt build")  # fmt: skip


class Busy(RuntimeError):
    """The machine is not fit to start a heavy job."""


class Overheated(RuntimeError):
    """A running heavy job was stopped by a kill switch."""


def _run(*cmd):
    try:
        return subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def reading():
    """The machine now. A key is None where macOS has no reading (or this isn't macOS)."""
    r = {"thermal": None, "battery_c": None, "speed_limit": None, "load_1": None,
         "cores": os.cpu_count(), "pressure": None, "swap_mb": None}  # fmt: skip
    state = _run("osascript", "-l", "JavaScript", "-e", THERMAL_JS).strip()
    if state.isdigit():
        r["thermal"] = THERMAL.get(int(state), "critical")
    if m := re.search(r'"Temperature" = (\d+)', _run("ioreg", "-rn", "AppleSmartBattery")):
        r["battery_c"] = int(m.group(1)) / 100
    if therm := _run("pmset", "-g", "therm"):
        m = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", therm)
        r["speed_limit"] = int(m.group(1)) if m else 100
    if m := re.search(r"\{\s*([\d.]+)", _run("sysctl", "-n", "vm.loadavg")):
        r["load_1"] = float(m.group(1))
    level = _run("sysctl", "-n", "kern.memorystatus_vm_pressure_level").strip()
    if level.isdigit():
        r["pressure"] = PRESSURE.get(int(level), "critical")
    if m := re.search(r"used = ([\d.]+)M", _run("sysctl", "-n", "vm.swapusage")):
        r["swap_mb"] = float(m.group(1))
    return r


def busy_processes(ps=None):
    """Container VMs and Dagster runs: `ps` lines matching BUSY."""
    ps = _run("ps", "-Ao", "pid,command") if ps is None else ps
    return [line.strip()[:120] for line in ps.splitlines() if BUSY.search(line)]


def too_busy(r, procs):
    """Why a heavy job shouldn't start now, or ""."""
    if r["load_1"] is not None and r["cores"] and r["load_1"] > r["cores"]:
        return f"load {r['load_1']:.1f} > {r['cores']} cores"
    if r["pressure"] not in (None, "normal"):
        return f"memory pressure {r['pressure']}"
    if r.get("thermal") in ("serious", "critical"):
        return f"thermal state {r['thermal']}"
    if procs:
        return f"busy: {procs[0]}"
    return ""


def hot(r):
    """Why the job should pause before its next unit, or ""."""
    if r.get("thermal") == "serious":
        return "thermal state serious"
    if r["speed_limit"] is not None and r["speed_limit"] < 100:
        return f"CPU throttled to {r['speed_limit']}%"
    if r["battery_c"] is not None and r["battery_c"] > BATTERY_MAX_C:
        return f"battery {r['battery_c']:.1f}°C > {BATTERY_MAX_C:.0f}°C"
    if r["pressure"] == "warn":
        return "memory pressure warn"
    return ""


def critical(r, swap_start):
    """Why the job must stop now, or ""."""
    if r.get("thermal") == "critical":
        return "thermal state critical"
    if r["pressure"] == "critical":
        return "memory pressure critical"
    if None not in (r["swap_mb"], swap_start) and r["swap_mb"] - swap_start > SWAP_GROWTH_MB:
        return f"swap grew {r['swap_mb'] - swap_start:.0f} MB"
    return ""


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def holder(lock=None):
    """The lock's record if a live process holds it, else None (a dead holder's lock is
    stale and removed)."""
    lock = lock or LOCK
    try:
        rec = json.loads(lock.read_text())
    except (FileNotFoundError, ValueError):
        return None
    if _alive(rec.get("pid", 0)):
        return rec
    lock.unlink(missing_ok=True)
    return None


def acquire(name, lock=None, **extra):
    """Take the lock for `name`. `extra` goes into the record (var, swap_start, detail)."""
    lock = lock or LOCK
    lock.parent.mkdir(parents=True, exist_ok=True)
    rec = {"job": name, "pid": os.getpid(), "started_at": datetime.now(UTC).isoformat(), **extra}
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            if held := holder(lock):
                raise Busy(f"{held['job']} (pid {held['pid']}) holds {lock}") from None
            continue
        with os.fdopen(fd, "w") as f:
            json.dump(rec, f)
        return rec
    raise Busy(f"could not take {lock}")


def release(lock=None):
    lock = lock or LOCK
    rec = holder(lock)
    if rec and rec["pid"] == os.getpid():
        lock.unlink(missing_ok=True)


def history_path(lock=None):
    return (lock or LOCK).with_name(HISTORY_NAME)


def record_end(rec, outcome, paused_s, lock=None):
    """Append the finished job to HISTORY."""
    end = {
        **rec,
        "ended_at": datetime.now(UTC).isoformat(),
        "outcome": outcome,
        "paused_s": paused_s,
    }
    with history_path(lock).open("a") as f:
        f.write(json.dumps(end) + "\n")


def unload_models():
    """`ollama stop` every loaded model; returns their names."""
    names = [ln.split()[0] for ln in _run("ollama", "ps").splitlines()[1:] if ln.strip()]
    for n in names:
        _run("ollama", "stop", n)
    return names


class Guard:
    """The running job's view of the watchdog."""

    def __init__(self, read=reading, sleep=time.sleep, max_wait=MAX_WAIT, step=PAUSE_STEP):
        self.read, self.sleep, self.max_wait, self.step = read, sleep, max_wait, step
        self.stop_reason = ""
        self.paused_s = 0.0
        self.outcome = ""  # set by the job to override "done" in HISTORY

    def check(self):
        """Call between units of work: pauses while hot, raises Overheated to stop."""
        waited = 0.0
        while True:
            if self.stop_reason:
                raise Overheated(self.stop_reason)
            why = hot(self.read())
            if not why:
                return
            if waited >= self.max_wait:
                self.stop_reason = f"{why} for {waited / 60:.0f} min"
                raise Overheated(self.stop_reason)
            print(f"  cooling: {why}; waiting {self.step}s", flush=True)
            self.sleep(self.step)
            waited += self.step
            self.paused_s += self.step


def _watch(guard, done, on_stop, swap_start, every):
    while not done.wait(every):
        if why := critical(guard.read(), swap_start):
            guard.stop_reason = why
            on_stop(why)
            return


@contextmanager
def job(name, force="", on_stop=None, read=reading, lock=None, every=WATCH_EVERY, detail=None):
    """Hold the heavy-job lock for `name` with a watchdog. `force` (a reason) skips the
    preflight, never the lock. `on_stop(reason)` runs from the watchdog thread when a
    critical reading stops the job; the job sees it on its next `guard.check()`. `detail`
    (e.g. the label and sample size) goes into the lock record for the monitor."""
    guard = Guard(read=read)
    if os.environ.get("CI"):
        yield guard
        return
    r = read()
    if why := too_busy(r, busy_processes()):
        if not force:
            raise Busy(f"{why}; wait, or pass --force <reason>")
        print(f"heavy: starting {name} anyway ({why}): {force}", flush=True)
    rec = acquire(name, lock, var=str(config.VAR), swap_start=r["swap_mb"], detail=detail or {})
    outcome = "failed"
    done = threading.Event()
    watcher = threading.Thread(
        target=_watch, args=(guard, done, on_stop or (lambda why: None), r["swap_mb"], every),
        daemon=True,
    )  # fmt: skip
    watcher.start()
    try:
        yield guard
        outcome = guard.outcome or "done"
    except Overheated:
        outcome = f"stopped: {guard.stop_reason}"
        unload_models()
        raise
    except KeyboardInterrupt:
        outcome = "interrupted"
        raise
    finally:
        done.set()
        release(lock)
        record_end(rec, outcome, guard.paused_s, lock)


def run(name, cmd, force=""):
    """Run `cmd` as heavy job `name`; a critical reading interrupts its process group,
    then terminates it 60 s later. Returns its exit code."""
    proc = None

    def stop(why):
        print(f"\nheavy: stopping {name}: {why}", flush=True)
        if proc and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGINT)
            try:
                proc.wait(60)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGTERM)

    with job(name, force=force, on_stop=stop, detail={"cmd": " ".join(cmd)[:200]}) as guard:
        proc = subprocess.Popen(cmd, start_new_session=True)
        try:
            code = proc.wait()
        except KeyboardInterrupt:
            os.killpg(proc.pid, signal.SIGINT)
            code = proc.wait()
        if code:
            guard.outcome = f"exit {code}"
        if guard.stop_reason:
            guard.outcome = f"stopped: {guard.stop_reason}"
            unload_models()
            _cancel_fight(name, guard.stop_reason)
            print(f"heavy: {name} stopped ({guard.stop_reason}); models unloaded", flush=True)
    return code


def _cancel_fight(name, reason):
    """Give the fight this run stopped its reason (the runner wrote "interrupted")."""
    if name != "fight":
        return
    records = sorted((config.VAR / "evals").glob("*.run.json"), key=lambda p: p.stat().st_mtime)
    if not records:
        return
    rec = json.loads(records[-1].read_text())
    if rec.get("status") in ("running", "cancelled"):
        rec.update(status="cancelled", reason=f"kill switch: {reason}")
        rec.setdefault("ended_at", datetime.now(UTC).isoformat())
        records[-1].write_text(json.dumps(rec, indent=2) + "\n")
