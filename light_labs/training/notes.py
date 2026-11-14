"""PJ's notes about his week: events no calendar shows, chores, being sick or sore.

`/note <text>` and `/replan <text>` in Rush's chat (`lab training note`). A local model
turns the text into rows; code resolves the day words to dates and checks every field.
Rush texts back what it understood, so a misread shows before the plan does.

What a row does to the plan (`apply`), all of it in code:

- start and end on an upcoming day: that time leaves the day's free windows.
- sick: the day has no free windows and the week owes one session fewer per sick day.
- chore, ache, travel: handed to the planner as context (kind, date, minutes, effort).

The raw text and each row's `what` stay on this machine. The planner's Claude call gets
kinds, dates and durations only, as the `training/plan` gate source declares. In work
hours no local model runs, so a note is saved unread and Rush's first tick after them
reads it.

Notes are append-only in var/training/notes/notes.jsonl; `/note undo` voids the newest.
"""

import json
import os
import re
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path

from light_labs import config
from light_labs.core import workhours

# An Ollama tag, not a brain spec: a note's text never goes to a paid model.
MODEL = os.environ.get("TRAINING_NOTES_MODEL", "llama3.1:8b")
KINDS = ("event", "chore", "sick", "ache", "travel", "other")
EFFORTS = ("light", "moderate", "hard")
DEFAULT_EVENT_MIN = 60  # an event with a start and no end or duration
CONTEXT_BEFORE = timedelta(days=7)  # last week's chores and aches still matter
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
_HHMM = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")

SYSTEM = """You turn PJ's note about his week into JSON for his training planner.
Reply with a JSON array only, no prose. One object per separate thing in the note:

{"kind": "event" | "chore" | "sick" | "ache" | "travel" | "other",
 "day": "...", "end_day": null, "start": null, "end": null,
 "minutes": null, "effort": null, "done": false, "what": "..."}

kind: event = an appointment or commitment at a time. chore = physical work (yardwork,
moving, cleaning, repairs). sick = ill: a cold, flu, fever, stomach bug, "sick".
ache = sore, tired, slept badly, a tweak or minor injury. travel = away from home.
day: the day exactly as he said it, lowercase: today, yesterday, tomorrow, a weekday
(mon tue wed thu fri sat sun) or YYYY-MM-DD. Use "today" when he names no day.
end_day: the last day when it spans several days, else null.
start, end: 24-hour "HH:MM" when he gives a time, else null. Hours 1 to 7 with no am/pm
are afternoon (3 = 15:00).
minutes: the duration in minutes when he gives one, else null.
effort: "light", "moderate" or "hard" for a chore, else null.
done: true when it already happened, false when it is coming up or ongoing.
what: 2 to 6 words.
One thing is one object, even when he adds detail about it. A trip is one object with day
and end_day. The same event on two days is two objects.

Examples (today is Wednesday):
Note: vet appointment Fri 4-5, and I power-washed the deck for 90 minutes on Monday
[{"kind":"event","day":"fri","end_day":null,"start":"16:00","end":"17:00","minutes":60,"effort":null,"done":false,"what":"vet appointment"},
 {"kind":"chore","day":"mon","end_day":null,"start":null,"end":null,"minutes":90,"effort":"moderate","done":true,"what":"power-washed the deck"}]
Note: at a conference Mon to Wed next week
[{"kind":"travel","day":"mon","end_day":"wed","start":null,"end":null,"minutes":null,"effort":null,"done":false,"what":"conference"}]
Note: headache, skipped lunch
[{"kind":"ache","day":"today","end_day":null,"start":null,"end":null,"minutes":null,"effort":null,"done":false,"what":"headache"}]
Note: came down with the flu yesterday
[{"kind":"sick","day":"yesterday","end_day":null,"start":null,"end":null,"minutes":null,"effort":null,"done":false,"what":"flu"}]
Note: school play 2026-12-03 at 6pm
[{"kind":"event","day":"2026-12-03","end_day":null,"start":"18:00","end":null,"minutes":null,"effort":null,"done":false,"what":"school play"}]"""


def path(var=None):
    return Path(var or config.VAR) / "training" / "notes" / "notes.jsonl"


# --- text to rows ----------------------------------------------------------------------


def resolve(word, today, done=False, after=None):
    """A day word as a date, or None. A weekday is the last one when `done`, else the
    next (today counts); with `after` (a span's first day), the first on or after it."""
    word = str(word or "").strip().lower()
    if _ISO.fullmatch(word):
        try:
            return date.fromisoformat(word)
        except ValueError:
            return None
    if word in ("today", "tonight"):
        return today
    if word == "yesterday":
        return today - timedelta(days=1)
    if word == "tomorrow":
        return today + timedelta(days=1)
    if word[:3] in _DAYS:
        base = after or today
        gap = (_DAYS.index(word[:3]) - base.weekday()) % 7
        if done and gap and not after:
            gap -= 7
        return base + timedelta(days=gap)
    return None


def _hhmm(value):
    m = _HHMM.fullmatch(str(value or "").strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def _plus(hhmm, minutes):
    total = min(int(hhmm[:2]) * 60 + int(hhmm[3:]) + minutes, 23 * 60 + 59)
    return f"{total // 60:02d}:{total % 60:02d}"


def clean(raw, today):
    """One model object as a row with every field checked, or None when it isn't one."""
    if not isinstance(raw, dict):
        return None
    done = raw.get("done") is True
    day = resolve(raw.get("day"), today, done) or today
    end_day = resolve(raw.get("end_day"), today, after=day) if raw.get("end_day") else None
    minutes = raw.get("minutes")
    minutes = minutes if isinstance(minutes, int) and 0 < minutes <= 24 * 60 else None
    start, end = _hhmm(raw.get("start")), _hhmm(raw.get("end"))
    if start and not end:
        end = _plus(start, minutes or DEFAULT_EVENT_MIN)
    if not start or end <= start:
        start = end = None
    kind = raw.get("kind") if raw.get("kind") in KINDS else "other"
    return {
        "kind": kind,
        "date": day.isoformat(),
        "end_date": end_day.isoformat() if end_day and end_day > day else None,
        "start": start,
        "end": end,
        "minutes": minutes,
        "effort": raw.get("effort") if raw.get("effort") in EFFORTS else None,
        "done": done or day < today,
        "what": str(raw.get("what") or kind)[:60],
    }


def parse(text, today, brain=None):
    """Rows for one note. ValueError when the model's reply has no JSON array."""
    from light_labs.core.brain import Brain

    brain = brain or Brain(MODEL)
    try:
        reply = brain.think(SYSTEM, f"Today is {today:%A} {today.isoformat()}.\nNote: {text}", 0)
    finally:
        if isinstance(brain, Brain):
            brain.unload()
    a, b = reply.find("["), reply.rfind("]")
    if a < 0 or b < a:
        raise ValueError("no JSON array in the reply")
    rows = [clean(r, today) for r in json.loads(reply[a : b + 1])]
    return [r for r in rows if r]


# --- the record ------------------------------------------------------------------------


def _append(record, var=None):
    p = path(var)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(record) + "\n")


def load(var=None):
    """Notes in order, newest state: voided ones dropped, late readings folded in."""
    notes = {}
    p = path(var)
    for line in p.read_text().splitlines() if p.exists() else []:
        r = json.loads(line)
        if "void" in r:
            notes.pop(r["void"], None)
        elif "read" in r:
            if r["read"] in notes:
                notes[r["read"]] = {**notes[r["read"]], "rows": r["rows"], "model": r["model"]}
        else:
            notes[r["id"]] = r
    return list(notes.values())


def add(text, now=None, var=None, parser=None, replan=False, defer=None):
    """Save a note and read it; in work hours (`defer`) save it unread (rows None)."""
    now = now or datetime.now()
    defer = workhours.working(now=now) if defer is None else defer
    rows = None if defer else (parser or parse)(text, now.date())
    record = {
        "id": f"n{now:%Y%m%d%H%M%S}-{secrets.token_hex(2)}",
        "at": now.isoformat(timespec="seconds"),
        "text": text,
        "rows": rows,
        "model": None if defer else MODEL,
        "replan": replan,
    }
    _append(record, var)
    return record


def read_unread(now=None, var=None, parser=None):
    """Read the notes saved in work hours. Returns them, read; [] in work hours."""
    now = now or datetime.now()
    if workhours.working(now=now):
        return []
    out = []
    for note in load(var):
        if note["rows"] is None:
            # Day words mean what they meant when he wrote the note.
            rows = (parser or parse)(note["text"], datetime.fromisoformat(note["at"]).date())
            _append({"read": note["id"], "rows": rows, "model": MODEL, "at": now.isoformat()}, var)
            out.append({**note, "rows": rows})
    return out


def undo(now=None, var=None):
    """Void the newest note; returns it, or None when there is none."""
    notes = load(var)
    if not notes:
        return None
    at = (now or datetime.now()).isoformat(timespec="seconds")
    _append({"void": notes[-1]["id"], "at": at}, var)
    return notes[-1]


def rows_for(start, var=None):
    """Rows touching the week starting `start`, or the week before it."""
    lo, hi = start - CONTEXT_BEFORE, start + timedelta(days=6)
    out = []
    for note in load(var):
        for r in note["rows"] or []:
            first = date.fromisoformat(r["date"])
            last = date.fromisoformat(r["end_date"]) if r["end_date"] else first
            if first <= hi and last >= lo:
                out.append(r)
    return out


# --- what a row does -------------------------------------------------------------------


def _span(row):
    first = date.fromisoformat(row["date"])
    last = date.fromisoformat(row["end_date"]) if row["end_date"] else first
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def apply(ctx, rows, train, subtract):
    """(ctx with busy times and sick days out of the free windows, sessions owed,
    context lines for the planner). `subtract` is plan.subtract."""
    busy, sick = {}, set()
    for r in rows:
        if r["kind"] == "sick":
            sick.update(_span(r))
        elif r["start"] and not r["done"]:
            busy.setdefault(r["date"], []).append([r["start"], r["end"]])
    days = []
    for d in ctx["days"]:
        free = [] if d["date"] in sick else d["free"]
        for window in busy.get(d["date"], []):
            free = subtract(free, window)
        days.append({**d, "free": free})
    dates = {d["date"] for d in days}
    owed = max(0, train - len(sick & dates))
    owed = min(owed, sum(1 for d in days if d["free"]))
    return {**ctx, "days": days}, owed, [line(r) for r in rows if r["kind"] != "event"]


def line(row):
    """A row for the planner's prompt: kind, dates and size. Never the note's words."""
    when = row["date"] + (f" to {row['end_date']}" if row["end_date"] else "")
    parts = [when, row["kind"]]
    if row["minutes"]:
        parts.append(f"{row['minutes']} min")
    if row["effort"]:
        parts.append(row["effort"])
    if row["kind"] != "sick":
        parts.append("done" if row["done"] else "upcoming")
    return " ".join(parts)


def _day(iso):
    return f"{date.fromisoformat(iso):%a %b %-d}"


def echo(rows):
    """What Rush understood, for PJ to check."""
    if not rows:
        return "I couldn't find anything to log in that. Try again with a day and what it is."
    out = []
    for r in rows:
        when = _day(r["date"]) + (f" to {_day(r['end_date'])}" if r["end_date"] else "")
        size = f", {r['minutes']} min" if r["minutes"] else ""
        if r["kind"] == "sick":
            out.append(f"{when}: sick ({r['what']}). No session; the week owes one fewer per day.")
        elif r["start"] and not r["done"]:
            out.append(f"{when} {r['start']}–{r['end']} busy ({r['what']})")
        else:
            effort = f", {r['effort']}" if r["effort"] else ""
            state = "done" if r["done"] else "upcoming"
            out.append(f"{when}: {r['what']} ({r['kind']}{size}{effort}, {state})")
    return "Got it:\n" + "\n".join(f"• {x}" for x in out) + "\n/note undo if I misread."
