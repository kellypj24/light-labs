"""Getting the weekly plan to PJ, and asking for the files it needs.

Rush's hourly tick calls `tick`. It:

1. Refreshes the plan when a file Rush asked for has arrived and Dagster has loaded it:
   the whole of next week before it starts, else the current week's remaining days.
2. On Sunday from 18:00, checks the inputs: Strong is stale when the newest export is
   over 6 days old, Health when no drop has come in 36 hours (the nightly Shortcut failed,
   or the Mac or Tailscale was off). For each stale one Rush texts how to send it. The
   plan for next week goes out once a Strong export lands that day, or at 20:00 with
   what there is, its first line saying what it was built without.
3. Daily from 21:00, asks for Health if it is stale.

Only requested files trigger a refresh, so the nightly Health drop never re-plans. State
lives in var/training/deliver.json; a lock keeps the tick and a Telegram-triggered
refresh from planning at once.
"""

import fcntl
import json
import re
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from light_labs import config
from light_labs.training import context as week_context

STRONG_STALE = timedelta(days=6)
HEALTH_STALE = timedelta(hours=36)
SUNDAY, CHECK_HOUR, PLAN_HOUR, LAST_HOUR, HEALTH_HOUR = 6, 18, 20, 23, 21
TELEGRAM_LIMIT = 4000
ASK = {
    "strong": "No Strong export since {since}. Strong → Export Data → share it to me here.",
    "health": "No Health workouts since {since}. Health Exporter → Export Workouts "
    "(Last 7 Days) → share it to me here.",
}
_STRONG = re.compile(r"^strong-(\d{4}-\d{2}-\d{2})\.csv$")
_HEALTH = re.compile(r"^health-(\d{4}-\d{2}-\d{2}-\d{6})\.json$")


def home(var=None):
    return Path(var or config.VAR) / "training"


@contextmanager
def _locked(var=None):
    path = home(var) / "deliver.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(home(var) / "deliver.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(path.read_text()) if path.exists() else {}
        state.setdefault("sent", {})
        state.setdefault("requested", {})
        yield state
        path.write_text(json.dumps(state, indent=2) + "\n")


def requested(var=None):
    """Kinds Rush has asked PJ to send and not yet received."""
    path = home(var) / "deliver.json"
    return json.loads(path.read_text()).get("requested", {}) if path.exists() else {}


def latest(var=None):
    """{'strong': newest export date, 'health': newest drop time}, None when there is none."""
    out = {"strong": None, "health": None}
    for kind, pattern, parse in (
        ("strong", _STRONG, date.fromisoformat),
        ("health", _HEALTH, lambda s: datetime.strptime(s, "%Y-%m-%d-%H%M%S")),
    ):
        for folder in (home(var) / kind, home(var) / kind / "inbox"):
            for p in folder.glob("*") if folder.exists() else []:
                m = pattern.match(p.name)
                if m:
                    at = parse(m.group(1))
                    if out[kind] is None or at > out[kind]:
                        out[kind] = at
    return out


def stale(newest, now):
    out = []
    if newest["strong"] is None or now.date() - newest["strong"] > STRONG_STALE:
        out.append("strong")
    if newest["health"] is None or now - newest["health"] > HEALTH_STALE:
        out.append("health")
    return out


def loaded(kind, var=None):
    """Dagster has taken every drop of `kind` out of its inbox."""
    box = home(var) / kind / "inbox"
    return not box.exists() or not any(box.iterdir())


def split(text, limit=TELEGRAM_LIMIT):
    """Messages under Telegram's limit, cut at blank lines (between days)."""
    out, cur = [], ""
    for block in text.split("\n\n"):
        piece = (cur + "\n\n" + block) if cur else block
        if len(piece) <= limit:
            cur = piece
        else:
            if cur:
                out.append(cur)
            cur = block[:limit]
    return [*out, cur] if cur else out


def _arrived(at, asked):
    """A drop at `at` (a date for Strong, a time for Health) answers a request made at
    `asked`. A Strong export is dated by day, so any export from that day on counts."""
    if at is None:
        return False
    return at >= (asked.date() if isinstance(at, date) and not isinstance(at, datetime) else asked)


def _since(newest, kind):
    at = newest[kind]
    return "ever" if at is None else f"{at:%a %b %-d}"


def _send_plan(path, send, lead):
    text = path.read_text()
    for i, part in enumerate(split(text)):
        send(None, f"{lead}\n\n{part}" if i == 0 else part)


def _week_key(start):
    year, num, _ = start.isocalendar()
    return f"{year}-W{num:02d}"


def _plan(state, start, send, planner, lead, from_date=None, built_without=()):
    key = _week_key(start)
    try:
        path, fails = planner(key, from_date=from_date)
    except Exception as e:  # noqa: BLE001 - any failure is texted, and retried next tick
        send(None, f"Couldn't plan {key}: {e}. I'll try again next hour.")
        state["error"] = {"week": key, "at": datetime.now().isoformat(timespec="minutes")}
        return False
    if built_without:
        missing = " and ".join(k.title() for k in built_without)
        lead += f" Built without a fresh {missing} export; send it and I'll update the plan."
    _send_plan(path, send, lead)
    state["sent"][key] = {
        "at": datetime.now().isoformat(timespec="minutes"),
        "from": from_date.isoformat() if from_date else None,
        "without": list(built_without),
        "failed_checks": len(fails),
    }
    state.pop("error", None)
    return True


def refresh(state, now, send, planner):
    """Replan after a requested file: next week whole before it starts, else this week's
    remaining days (from today before noon, else tomorrow)."""
    nxt = week_context.week_start(today=now.date())
    if _week_key(nxt) in state["sent"]:
        return _plan(state, nxt, send, planner, "Updated plan:")
    this = nxt - timedelta(days=7)
    start_from = now.date() if now.hour < 12 else now.date() + timedelta(days=1)
    if start_from > this + timedelta(days=6):
        return False
    from_date = start_from if start_from > this else None
    return _plan(state, this, send, planner, "Updated plan for the rest of the week:", from_date)


def tick(send, now=None, planner=None, var=None):
    """One pass; returns what it did, for the journal."""
    if planner is None:
        from light_labs.training import plan

        planner = plan.run
    now = now or datetime.now()
    done = []
    with _locked(var) as state:
        newest = latest(var)
        arrived = [
            kind
            for kind, asked in state["requested"].items()
            if _arrived(newest[kind], datetime.fromisoformat(asked)) and loaded(kind, var)
        ]
        for kind in arrived:
            del state["requested"][kind]
        if arrived and refresh(state, now, send, planner):
            done.append(f"refreshed after {', '.join(arrived)}")

        missing = stale(newest, now)
        nxt = week_context.week_start(today=now.date())
        if (
            now.weekday() == SUNDAY
            and CHECK_HOUR <= now.hour <= LAST_HOUR
            and _week_key(nxt) not in state["sent"]
        ):
            for kind in missing:
                if kind not in state["requested"]:
                    send(None, ASK[kind].format(since=_since(newest, kind)))
                    state["requested"][kind] = now.isoformat(timespec="minutes")
                    done.append(f"asked for {kind}")
            fresh_strong = newest["strong"] == now.date() and loaded("strong", var)
            due = fresh_strong or now.hour >= PLAN_HOUR
            if due and _plan(state, nxt, send, planner, "Next week's plan:", built_without=missing):
                done.append(f"sent {_week_key(nxt)}")

        if (
            now.hour >= HEALTH_HOUR
            and "health" in missing
            and "health" not in state["requested"]
            and state.get("health_asked") != now.date().isoformat()
        ):
            send(None, ASK["health"].format(since=_since(newest, "health")))
            state["requested"]["health"] = now.isoformat(timespec="minutes")
            state["health_asked"] = now.date().isoformat()
            done.append("asked for health")
    return done


def replan(send, now=None, planner=None, var=None):
    """`/replan` on Telegram: refresh whatever week is current, now."""
    if planner is None:
        from light_labs.training import plan

        planner = plan.run
    now = now or datetime.now()
    with _locked(var) as state:
        if not refresh(state, now, send, planner):
            send(None, "Nothing left to plan this week.")


def send_week(week, send, var=None):
    """`lab training send`: text an existing plan."""
    start = week_context.week_start(week)
    path = home(var) / "plans" / f"{_week_key(start)}.md"
    if not path.exists():
        raise FileNotFoundError(f"no plan at {path}; run `lab training plan` first")
    _send_plan(path, send, f"Plan for {_week_key(start)}:")
    return path
