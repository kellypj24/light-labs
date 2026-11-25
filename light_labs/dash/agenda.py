"""Today's calendar events for the dashboard.

Read through the `dash` Google sign-in (calendar.events.readonly; core/google.py). The
account and calendar names come from DASH_GOOGLE_ACCOUNT and DASH_CALENDARS in .env,
falling back to the training planner's (TRAINING_GOOGLE_ACCOUNT, TRAINING_CALENDARS).
Titles are shown in the terminal and nowhere else.
"""

import os
import re
from datetime import UTC, date, datetime, time, timedelta

from light_labs.training.calendar import TZ

URL = re.compile(r"https://[^\s<>\"']+")


class NotSignedIn(RuntimeError):
    pass


def account():
    return os.environ.get("DASH_GOOGLE_ACCOUNT") or os.environ.get("TRAINING_GOOGLE_ACCOUNT", "")


def calendar_names():
    raw = os.environ.get("DASH_CALENDARS") or os.environ.get("TRAINING_CALENDARS", "primary")
    return [n.strip() for n in raw.split(",") if n.strip()]


def _when(point):
    """(aware datetime, all_day) from an event's start or end."""
    if "dateTime" in point:
        at = datetime.fromisoformat(point["dateTime"])
        return (at if at.tzinfo else at.replace(tzinfo=TZ)).astimezone(TZ), False
    return datetime.combine(date.fromisoformat(point["date"]), time(0), TZ), True


def _declined(item):
    mine = [a for a in item.get("attendees") or [] if a.get("self")]
    return any(a.get("responseStatus") == "declined" for a in mine)


def _unanswered(item):
    mine = [a for a in item.get("attendees") or [] if a.get("self")]
    return any(a.get("responseStatus") == "needsAction" for a in mine)


def _link(item):
    """(url, is a join link). Only https links are ever opened."""
    for candidate in (item.get("hangoutLink"), item.get("location")):
        if m := URL.search(candidate or ""):
            return m.group(0), True
    if m := URL.fullmatch(item.get("htmlLink") or ""):
        return m.group(0), False
    return "", False


def normalize(item, calendar):
    """One Google event as the dashboard's row, or None for one that isn't shown."""
    if item.get("status") == "cancelled" or _declined(item):
        return None
    try:
        start, all_day = _when(item["start"])
        end, _ = _when(item["end"])
    except (KeyError, TypeError, ValueError):
        return None
    url, join = _link(item)
    return {
        "id": item.get("id", ""),
        "title": " ".join(str(item.get("summary") or "(no title)").split()),
        "start": start,
        "end": end,
        "all_day": all_day,
        "calendar": calendar,
        "url": url,
        "join": join,
        "unanswered": _unanswered(item),
    }


def fetch(day=None, cal=None, names=None):
    """Today's events across the named calendars: all-day first, then by start."""
    if cal is None:
        from light_labs.core.google import EventCalendar

        if not account():
            raise NotSignedIn("DASH_GOOGLE_ACCOUNT is not set in .env")
        cal = EventCalendar("dash", account())
    names = names or calendar_names()
    day = day or datetime.now(TZ).date()
    start = datetime.combine(day, time(0), TZ)
    end = start + timedelta(days=1)
    seen, out = set(), []
    for name, cid in zip(names, cal.resolve(names), strict=True):
        for item in cal.events(cid, start, end):
            event = normalize(item, name)
            # An invite accepted on two calendars is one event.
            key = (event["title"], event["start"], event["end"]) if event else None
            if event and key not in seen:
                seen.add(key)
                out.append(event)
    out.sort(key=lambda e: (not e["all_day"], e["start"].timestamp(), e["end"].timestamp()))
    return out


def _span(seconds):
    minutes = max(1, round(seconds / 60))
    return f"{minutes}m" if minutes < 60 else f"{minutes // 60}h{minutes % 60:02d}m"


def countdown(event, now):
    if event["all_day"]:
        return "today"
    # In UTC: two times in the same zone compare by wall clock, which is wrong across a
    # daylight-saving change.
    now, start, end = (t.astimezone(UTC) for t in (now, event["start"], event["end"]))
    if now >= end:
        return "done"
    if now >= start:
        return "now"
    return "in " + _span((start - now).total_seconds())


def rows(events, now):
    """Events as displayed: a row number, the time, a countdown, and `focus` on the
    current event or else the next one."""
    out, focus = [], None
    for n, e in enumerate(events, 1):
        state = countdown(e, now)
        if focus is None and state == "now":
            focus = n
        out.append(
            {
                **e,
                "n": n,
                "time": "all day" if e["all_day"] else f"{e['start']:%H:%M}-{e['end']:%H:%M}",
                "countdown": state,
            }
        )
    if focus is None:
        focus = next((r["n"] for r in out if r["countdown"].startswith("in ")), None)
    for r in out:
        r["focus"] = r["n"] == focus
    return out
