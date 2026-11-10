"""PJ's work hours on this laptop, when Teams and Memex need the memory.

Inside them no robot loads a local model and no heavy job starts without `--force`
(`just check` excepted): Rush drafts and triages through Claude, personal mail waits for
the evening, Roll sits out of chores. LAB_WORK_HOURS is "HH:MM-HH:MM" on weekdays,
default 08:00-17:00; empty turns it off.
"""

import os
from datetime import datetime

from light_labs import config  # noqa: F401 - loads .env before LAB_WORK_HOURS is read

DEFAULT = "08:00-17:00"


def _minutes(hhmm):
    h, _, m = hhmm.strip().partition(":")
    return int(h) * 60 + int(m or 0)


def working(hours=None, now=None):
    """True on a weekday inside `hours` (default LAB_WORK_HOURS)."""
    hours = os.environ.get("LAB_WORK_HOURS", DEFAULT) if hours is None else hours
    if not hours:
        return False
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    start, end = (_minutes(p) for p in hours.split("-"))
    return start <= now.hour * 60 + now.minute < end
