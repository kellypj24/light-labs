"""How Rush learns a digest is ready without reading Radar's data.

`lab radar weekly` leaves a marker under the lab's var/ holding the digest's date and
nothing else. Rush's hourly tick texts the page's link (radar/page.py) once per new date.
The process that holds the database gets no bot token and no outbound call; Rush gets no
path into Radar's folder. Stdlib only, and no import from the rest of radar/.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

TEXT = "Weekly picks are ready."


def _dir(var=None) -> Path:
    if var is None:
        from light_labs import config

        var = config.VAR
    return Path(var) / "radar"


def ready_path(var=None) -> Path:
    return _dir(var) / "ready.json"


def notified_path(var=None) -> Path:
    return _dir(var) / "notified.json"


def _read(path: Path) -> str | None:
    """The file's date as ISO text, or None when it is absent or not a date: the marker
    sits in a folder other code can write, so nothing but a date is taken from it."""
    try:
        return date.fromisoformat(json.loads(path.read_text())["date"]).isoformat()
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write(path: Path, day: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"date": day}) + "\n")
    tmp.replace(path)


def mark(day: date, var=None) -> Path:
    """A digest for `day` is on the page."""
    path = ready_path(var)
    _write(path, day.isoformat())
    return path


def link() -> str:
    """The page's tailnet address, or '' when `RADAR_URL` is unset."""
    return os.environ.get("RADAR_URL", "").rstrip("/")


def tick(send, var=None) -> list[str]:
    """Text the link when the marker names a date not yet texted; returns what it did,
    for the journal. Without `RADAR_URL` nothing is sent and the date stays unsent."""
    day = _read(ready_path(var))
    url = link()
    if not day or not url or day == _read(notified_path(var)):
        return []
    send(None, f"{TEXT}\n\n{url}")
    _write(notified_path(var), day)
    return [f"texted the page link for {day}"]


def clear(var=None) -> list[Path]:
    """The marker files, for `lab radar purge`."""
    return [ready_path(var), notified_path(var)]
