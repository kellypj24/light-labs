"""LaunchAgents for the daily sync and the weekly digest.

They run `lab radar` from the deployed release (`lab deploy radar`, a fixed commit of
origin/main with its own locked environment), never from a checkout: a branch someone
left checked out, or a dependency resolved at run time, would otherwise run at 06:30 with
the database in reach. They need no special permission: only the helper (its own
LaunchAgent, 06:20) reads Messages and Contacts.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

from light_labs import deploy
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


def release_lab() -> Path:
    """`lab` in the deployed release's environment."""
    return deploy.TARGETS["radar"] / "current" / ".venv" / "bin" / "lab"


def plist(job: str, paths: Paths, lab: Path) -> dict[str, object]:
    when, args = JOBS[job]
    log = str(paths.logs / f"{job}.log")
    return {
        "Label": label(job),
        "ProgramArguments": [str(lab), "radar", *args],
        "StartCalendarInterval": when,
        "RunAtLoad": False,
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "EnvironmentVariables": {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        "ProcessType": "Background",
    }


def install(paths: Paths) -> list[Path]:
    lab = release_lab()
    if not lab.exists():
        raise FileNotFoundError(f"{lab} is missing: run `lab deploy radar` first")
    paths.ensure()
    out = []
    for job in JOBS:
        p = plist_path(job)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(plistlib.dumps(plist(job, paths, lab)))
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


def runs_release(job: str) -> bool:
    """Whether the installed LaunchAgent starts the release's `lab`."""
    p = plist_path(job)
    if not p.exists():
        return False
    args = plistlib.loads(p.read_bytes()).get("ProgramArguments") or [""]
    return args[0] == str(release_lab())
