"""Check-offs from the Workouts app (`training/app.py`): which sets and items PJ ticked.

An append-only log in var/training/checks.jsonl, one line per tap: the day, the item (a
hash of its exercise or text), the set number, and whether the tap checked it or undid
it. The newest line for a set is its state.

Strong and Health stay the record of what was trained. The log adds to it: it shows how
the app is used, and it is the only record of items no other app captures (bag rounds).
`training.record` lands it in DuckDB beside the plans' items.
"""

import hashlib
import json
import threading
from datetime import date, datetime

from light_labs.training import deliver


def plan(key, var=None):
    """A week's plan as the planner wrote it (glance, days, summary); None without JSON."""
    path = deliver.home(var) / "plans" / f"{key}.json"
    return json.loads(path.read_text()) if path.exists() else None


def plan_days(whole):
    return {d["date"]: d for d in (whole or {}).get("days", [])}


def item_key(item):
    """An item's id within its day: a hash of the exercise or text, so the same exercise
    keeps its check-offs when a replan reorders the day."""
    label = item.get("exercise") or item.get("text") or ""
    return hashlib.sha1(label.encode()).hexdigest()[:10]


def units(item):
    """How many buttons an item gets: one per set, one for anything else."""
    sets = item.get("sets")
    return sets if isinstance(sets, int) and 0 < sets <= 20 else 1


def checks_path(var=None):
    return deliver.home(var) / "checks.jsonl"


_checks_lock = threading.Lock()


def checks(var=None):
    """{(date, item key): {set numbers done}} from the log; a later line wins."""
    out = {}
    path = checks_path(var)
    for line in path.read_text().splitlines() if path.exists() else []:
        r = json.loads(line)
        done = out.setdefault((r["date"], r["item"]), set())
        (done.add if r["done"] else done.discard)(r["n"])
    return out


def check(day, key, n, done, var=None, at=None):
    """Log one check-off (or its undoing). ValueError unless the plan has that day, item
    and set, so the log holds only what a page could have shown."""
    try:
        week = deliver.week_key(date.fromisoformat(day))
    except ValueError:
        raise ValueError("no such day") from None
    items = {item_key(i): i for i in plan_days(plan(week, var)).get(day, {}).get("items", [])}
    if key not in items or not 1 <= n <= units(items[key]):
        raise ValueError("no such item")
    record = {
        "at": (at or datetime.now()).isoformat(timespec="seconds"),
        "date": day,
        "item": key,
        "n": n,
        "done": bool(done),
    }
    with _checks_lock:
        path = checks_path(var)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(record) + "\n")
