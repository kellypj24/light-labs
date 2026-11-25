"""What happened lately, newest first: the dashboard's RECENT section and `lab feed`.

Nothing is collected and nothing is written. Each event is read from a record its
producer already keeps with a timestamp:

- the robots' journals (var/<robot>/journal.md), minus their routine lines. Rush's
  GitHub watch journals each change it texts PJ about, so CI going red or green is here
- Dagster runs that failed or were canceled, from its run store
- eval runs that finished, from var/evals/*.run.json
- the last turn of each Claude Code session, from its log

History is as long as those records are. Journal text can name other people's mail and
PRs; like the calendar's titles it is drawn in the terminal and goes nowhere else.
"""

import json
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

from light_labs import config
from light_labs.dash import labstate, review, sessions

ROBOTS = ("rush", "roll")
LINE = re.compile(r"- (\S+) (.+)")
# Journal lines that record routine, not news.
ROUTINE = re.compile(
    r"tick: 0 draft|mail: |texted PJ about GitHub|training: asked|\w+ superseded by |texted PJ about [0-9a-f]{8}$"
)
BAD = re.compile(r"\bfailed\b|could not|unreachable|\bheld\b", re.IGNORECASE)
GOOD = re.compile(r"passing again")
SESSION_DAYS = 7  # how far back session logs are opened
BURST = timedelta(minutes=2)  # one check failing for five repos is one line
SPAN = re.compile(r"(\d+)\s*([mhdw])")
UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def span(text):
    """ "90m", "6h", "2d", "1w" as a timedelta."""
    m = SPAN.fullmatch(text.strip().lower())
    if not m or not int(m.group(1)):
        raise ValueError(f"not a time span (try 6h, 2d, 1w): {text}")
    return timedelta(**{UNITS[m.group(2)]: int(m.group(1))})


def _aware(stamp):
    at = datetime.fromisoformat(str(stamp))
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _event(at, source, text, level=""):
    return {"at": at, "source": source, "text": " ".join(str(text).split()), "level": level}


def _level(text):
    if GOOD.search(text):
        return "good"
    if not BAD.search(text):
        return ""
    # A canary going red is news, not a fault.
    quiet = any(f"({name})" in text.casefold() for name in review.canaries())
    return "" if quiet else "bad"


def journal(robot, since, var=None):
    path = (var or config.VAR) / robot / "journal.md"
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):  # appended in time order: stop at the first old one
        m = LINE.fullmatch(line)
        if not m:
            continue
        try:
            at = _aware(m.group(1))
        except ValueError:
            continue
        if at < since:
            break
        text = m.group(2).strip()
        if not ROUTINE.match(text):
            out.append(_event(at, robot, text.removeprefix("GitHub: "), _level(text)))
    return out


def dagster(since, db=None):
    db = labstate._dagster_db(db)
    if not db.exists():
        return []
    sql = (
        "SELECT pipeline_name, status, COALESCE(end_time, start_time) FROM runs "
        "WHERE status IN ('FAILURE', 'CANCELED') AND COALESCE(end_time, start_time) >= ?"
    )
    try:
        with closing(labstate._read_only(db)) as con:
            found = con.execute(sql, (since.timestamp(),)).fetchall()
    except sqlite3.Error:
        return []
    return [
        _event(datetime.fromtimestamp(at, UTC), "dagster", f"{name} {status.lower()}", "bad")
        for name, status, at in found
        if isinstance(at, (int, float))
    ]


def evals(since, var=None):
    out = []
    for path in ((var or config.VAR) / "evals").glob("*.run.json"):
        try:
            run = json.loads(path.read_text())
            at = _aware(run["ended_at"])
            stage, status = str(run["stage"]), str(run.get("status") or "?")
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if at < since:
            continue
        score = f" {run.get('passed')}/{run.get('done')}" if run.get("done") else ""
        done = status == "completed"
        out.append(_event(at, "evals", f"{stage} {status}{score}", "" if done else "bad"))
    return out


_turns = {}  # log path -> (mtime_ns, event or None)


def _last_turn(path, mtime_ns):
    if _turns.get(path, (None,))[0] != mtime_ns:
        records = sessions._tail(path)
        title = sessions.log_facts(records).get("title")
        at = None
        for rec in reversed(records):
            if rec.get("type") == "assistant" and not rec.get("isSidechain"):
                try:
                    at = _aware(rec["timestamp"])
                except (KeyError, ValueError):
                    at = datetime.fromtimestamp(mtime_ns / 1e9, UTC)
                break
        event = _event(at, "claude", f"{title}: turn ended") if at and title else None
        _turns[path] = (mtime_ns, event)
    return _turns[path][1]


def claude(since, projects=None, now=None):
    """The last turn of each session whose log changed lately. Earlier turns of the same
    session are not events: the log's tail is all that is read."""
    now = now or datetime.now(UTC)
    since = max(since, now - timedelta(days=SESSION_DAYS))
    out = []
    for path in (projects or sessions.CLAUDE / "projects").glob("*/*.jsonl"):
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            continue
        if mtime_ns / 1e9 < since.timestamp():
            continue
        event = _last_turn(path, mtime_ns)
        if event and event["at"] >= since:
            out.append(event)
    return out


def events(since, now=None):
    """Every event at or after `since`, newest first. A source that can't be read adds
    nothing."""
    readers = [lambda r=r: journal(r, since) for r in ROBOTS]
    readers += [lambda: dagster(since), lambda: evals(since), lambda: claude(since, now=now)]
    out = []
    for read in readers:
        try:
            out += read()
        except Exception:  # noqa: BLE001, S112 - one unreadable source must not empty the feed
            continue
    out.sort(key=lambda e: e["at"], reverse=True)
    return merged(out)


def merged(found):
    """Newest-first events with a burst folded into its newest line: the same source
    starting with the same three words within BURST of the line before."""
    out, heads = [], []
    for e in found:
        head = (e["source"], e["text"].split()[:3])
        if heads and heads[-1][0] == head and heads[-1][1] - e["at"] <= BURST:
            out[-1]["more"] += 1
            heads[-1] = (head, e["at"])
            continue
        out.append({**e, "more": 0})
        heads.append((head, e["at"]))
    for e in out:
        more = e.pop("more")
        if more:
            e["text"] = f"({more + 1}x) {e['text']}"
    return out
