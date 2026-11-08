"""LaunchAgents for the daily sync and the weekly digest.

They run `lab radar` from this checkout through uv, like Rush's tick, and need no special
permission: only the helper (its own LaunchAgent, 06:20) reads Messages and Contacts.
"""

from __future__ import annotations

import plistlib
import shutil
from pathlib import Path

from light_labs import config
from light_labs.radar import helper
from light_labs.radar.config import Paths

JOBS = {
    # 06:30 daily, after the helper's 06:20 export.
    "sync": ({"Hour": 6, "Minute": 30}, ["sync"]),
    # Friday 15:00 local time.
    "weekly": ({"Weekday": 5, "Hour": 15, "Minute": 0}, ["weekly"]),
}


def label(job: str) -> str:
    return f"com.pjkelly.relationship-radar.{job}"


def plist_path(job: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label(job)}.plist"


def plist(job: str, paths: Paths, uv: str) -> dict[str, object]:
    when, args = JOBS[job]
    log = str(paths.logs / f"{job}.log")
    return {
        "Label": label(job),
        "ProgramArguments": [uv, "run", "--project", str(config.REPO), "lab", "radar", *args],
        "StartCalendarInterval": when,
        "RunAtLoad": False,
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "ProcessType": "Background",
    }


def install(paths: Paths) -> list[Path]:
    uv = shutil.which("uv")
    if not uv:
        raise FileNotFoundError("uv not on PATH")
    paths.ensure()
    out = []
    for job in JOBS:
        p = plist_path(job)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(plistlib.dumps(plist(job, paths, uv)))
        helper._launchctl("bootout", f"{helper._domain()}/{label(job)}", check=False)
        helper._launchctl("bootstrap", helper._domain(), str(p))
        out.append(p)
    return out


def uninstall() -> None:
    for job in JOBS:
        helper._launchctl("bootout", f"{helper._domain()}/{label(job)}", check=False)
        plist_path(job).unlink(missing_ok=True)


def loaded(job: str) -> bool:
    r = helper._launchctl("print", f"{helper._domain()}/{label(job)}", check=False)
    return r.returncode == 0
