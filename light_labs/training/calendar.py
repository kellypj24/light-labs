"""Free windows per day from PJ's Google calendars, for the training planner.

The `training` Google sign-in has only `calendar.freebusy` and
`calendar.calendarlist.readonly`: busy blocks and calendar names, never an event's title,
attendees or notes. The family calendar (iCloud, subscribed in Google Calendar) is found
by name, so its events are other people's data that reach the lab only as busy time.

TRAINING_CALENDARS (comma-separated names, `primary` for the main calendar) and
TRAINING_GOOGLE_ACCOUNT come from .env.
"""

import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
DAY_START, DAY_END = time(5, 0), time(21, 0)
MIN_GAP = timedelta(minutes=45)


def calendar_names():
    names = [n.strip() for n in os.environ.get("TRAINING_CALENDARS", "primary").split(",")]
    return [n for n in names if n]


def _parse(text):
    at = datetime.fromisoformat(text)
    return at if at.tzinfo else at.replace(tzinfo=TZ)


def free_windows(busy, days, tz=TZ, start=DAY_START, end=DAY_END, min_gap=MIN_GAP):
    """{date: [(start, end), ...]} free gaps of at least `min_gap` between `start` and `end`
    local time on each of `days`. `busy` is [(start, end)] ISO strings from any calendar."""
    blocks = sorted((_parse(a).astimezone(tz), _parse(b).astimezone(tz)) for a, b in busy)
    out = {}
    for day in days:
        cursor = datetime.combine(day, start, tz)
        day_end = datetime.combine(day, end, tz)
        gaps = []
        for b_start, b_end in blocks:
            if b_end <= cursor or b_start >= day_end:
                continue
            if b_start - cursor >= min_gap:
                gaps.append((cursor, b_start))
            cursor = max(cursor, b_end)
        if day_end - cursor >= min_gap:
            gaps.append((cursor, day_end))
        out[day] = gaps
    return out


def fetch_busy(week_start, cal=None, names=None):
    """All busy blocks for the 7 days from `week_start` across the named calendars."""
    if cal is None:
        from light_labs.core.google import Calendar

        account = os.environ.get("TRAINING_GOOGLE_ACCOUNT", "")
        if not account:
            raise RuntimeError("TRAINING_GOOGLE_ACCOUNT is not set in .env")
        cal = Calendar("training", account)
    ids = cal.resolve(names or calendar_names())
    start = datetime.combine(week_start, time(0), TZ)
    by_calendar = cal.busy(ids, start, start + timedelta(days=7))
    return [block for blocks in by_calendar.values() for block in blocks]
