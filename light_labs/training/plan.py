"""The weekly training plan: Python decides the numbers, Claude writes the week around them.

`lab training plan [--week 2026-W47]` (default: next week) reads goals.md, the week's
context (free windows and weather, `training.context`), the lift and load marts, and the
last plan, then writes var/training/plans/<yyyy>-W<ww>.md.

Code owns what must be right: the week number and deload (goals.md: week 1 starts
2026-11-09, every 4th is a deload; also a deload when acute:chronic load is above 1.3),
and every lift's load and reps (progression from Strong's top sets: keep the rep scheme
PJ trains; matching last time's top set adds load, falling short repeats it). The model picks and places
sessions and writes them up, returning JSON that `check` validates: exactly 5 training
days, each session inside a free window, each outdoor run inside the day's outdoor hours,
lift loads from the table. A failed check gets one retry with the failures; then the plan
is written with them listed.

A midweek replan (`from_date`) plans only the days from that date, with as many training
days as the week still owes after what Strong and Health logged before it; the days
before it keep the earlier plan.
"""

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from light_labs import config
from light_labs.training import context as week_context

SOURCE = "training/plan"
MODEL = os.environ.get("TRAINING_PLAN_BRAIN", "claude:sonnet")
TRAINING_DAYS = 5
DELOAD_EVERY = 4
DELOAD_RATIO = 1.3
DELOAD_LOAD = 0.9
# Load steps: barbell plates in 5 lb; PowerBlock dumbbells in 2.5 lb per hand (Strong
# logs dumbbells per hand).
STEP_LB, DUMBBELL_STEP_LB = 5, 2.5
RECENT = timedelta(weeks=12)
# Until the work calendar is shared into TRAINING_CALENDARS, weekdays in this window are
# treated as busy. TRAINING_ASSUME_WORK= (empty) turns it off.
ASSUME_WORK = os.environ.get("TRAINING_ASSUME_WORK", "08:00-17:00")
_WEEK1 = re.compile(r"Week 1 starts \w+ (\d{4}-\d{2}-\d{2})")


def home(var=None):
    return Path(var or config.VAR) / "training"


# --- numbers code owns -----------------------------------------------------------------


def week_number(start, goals):
    m = _WEEK1.search(goals)
    if not m:
        raise LookupError("goals.md has no 'Week 1 starts <day> YYYY-MM-DD' line")
    return (start - date.fromisoformat(m.group(1))).days // 7 + 1


def deload(number, acute_chronic):
    """(is it a deload, why)."""
    if number % DELOAD_EVERY == 0:
        return True, f"week {number} is a scheduled deload (every {DELOAD_EVERY}th)"
    if acute_chronic is not None and acute_chronic > DELOAD_RATIO:
        return True, f"acute:chronic load is {acute_chronic:.2f}, above {DELOAD_RATIO}"
    return False, ""


def _round(x, step):
    return round(step * round(x / step), 1)


def progression(lifts, start, is_deload):
    """One row per exercise trained in the last 12 weeks: its last top set and next
    target. `lifts` are mart_lift_progress rows (dicts), any number of weeks each.

    The rep target is the scheme PJ trains: the more reps of the last two weeks' top sets.
    The last top set reaching it adds one step of load; falling short repeats the load.
    Bodyweight lifts add a rep instead. A deload takes 90% of the load."""
    by_exercise = {}
    for r in lifts:
        by_exercise.setdefault(r["exercise"], []).append(r)
    out = []
    for name, rows in by_exercise.items():
        rows.sort(key=lambda r: r["week_start"])
        latest, prev = rows[-1], (rows[-2] if len(rows) > 1 else None)
        last = latest["last_session_date"]
        if isinstance(last, datetime):
            last = last.date()
        if start - last > RECENT:
            continue
        weight, reps = latest["top_set_weight"] or 0, int(latest["top_set_reps"] or 0)
        if latest["is_bodyweight_lift"]:
            target_reps, load = reps + 1, None
            rule = f"bodyweight: {reps} → {target_reps} reps"
        else:
            target_reps = max(reps, int(prev["top_set_reps"] or 0) if prev else 0)
            step = DUMBBELL_STEP_LB if "(Dumbbell)" in name else STEP_LB
            hit = reps >= target_reps
            load = weight + step if hit else weight
            rule = (
                f"{weight:g}×{reps}, scheme {target_reps}: {'hit' if hit else 'short'} → {load:g}"
            )
            if is_deload:
                load = _round(load * DELOAD_LOAD, step)
                rule += f", deload {load:g}"
        out.append(
            {
                "exercise": name,
                "pattern": latest["movement_pattern"],
                "last": f"{weight:g}×{reps} on {last}",
                "reps": target_reps,
                "load_lb": load,
                "per_hand": "(Dumbbell)" in name,
                "rule": rule,
            }
        )
    return sorted(out, key=lambda x: (x["pattern"], x["exercise"]))


def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def subtract(windows, busy):
    """Free windows [["05:00","21:00"]] minus one busy [start, end]."""
    b0, b1 = (_minutes(x) for x in busy)
    out = []
    for a, b in windows:
        a0, a1 = _minutes(a), _minutes(b)
        for s, e in ((a0, min(a1, b0)), (max(a0, b1), a1)):
            if e - s >= 45:
                out.append([_hhmm(s), _hhmm(e)])
    return out


def with_assumed_work(ctx, assume=ASSUME_WORK):
    """Weekdays lose the assumed work hours until the work calendar is shared."""
    if not assume:
        return ctx
    busy = assume.split("-")
    days = []
    for d in ctx["days"]:
        weekday = date.fromisoformat(d["date"]).weekday() < 5
        days.append({**d, "free": subtract(d["free"], busy) if weekday else d["free"]})
    return {**ctx, "days": days, "assumed_work": assume}


# --- inputs ----------------------------------------------------------------------------


LOCK_WAIT, LOCK_STEP = 180, 5  # seconds; a Dagster job holds the write lock for minutes


def _connect(db=None, wait=LOCK_WAIT, sleep=None):
    """var/lab.duckdb read-only. DuckDB refuses a reader while another process has the
    file open for writing (a Dagster job), so wait for the writer instead of failing."""
    import time

    import duckdb

    sleep = sleep or time.sleep
    path, waited = str(db or config.VAR / "lab.duckdb"), 0
    while True:
        try:
            return duckdb.connect(path, read_only=True)
        except duckdb.IOException as e:
            if "lock" not in str(e).lower() or waited >= wait:
                raise
            sleep(LOCK_STEP)
            waited += LOCK_STEP


def read_marts(db=None):
    """(lift rows of the last 26 weeks, last 6 weeks of load) from var/lab.duckdb,
    read-only."""

    def rows(con, sql):
        cur = con.execute(sql)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    with _connect(db) as con:
        lifts = rows(
            con,
            "SELECT * FROM marts.mart_lift_progress "
            "WHERE week_start >= current_date - INTERVAL 26 WEEK",
        )
        weeks = rows(
            con,
            "SELECT iso_week, training_days, lifting_sessions, working_sets, tonnage_lb, "
            "cardio_sessions, cardio_minutes, cardio_miles, training_minutes, "
            "acute_chronic_ratio FROM marts.mart_training_weekly "
            "ORDER BY week_start DESC LIMIT 6",
        )
    return lifts, weeks


def done_days(start, before, db=None):
    """Training days logged in the week starting `start`, before `before`."""
    with _connect(db) as con:
        return con.execute(
            "SELECT count(DISTINCT session_date) FROM intermediate.int_training_sessions "
            "WHERE session_date >= ? AND session_date < ?",
            [start, before],
        ).fetchone()[0]


def last_plan(start, var=None):
    """The most recent plan or imported note before this week, as text."""
    candidates = []
    for folder in ("plans", "history"):
        for p in (home(var) / folder).glob("*-W*.md"):
            year, _, num = p.stem.partition("-W")
            if year.isdigit() and num.isdigit():
                monday = date.fromisocalendar(int(year), int(num), 1)
                if monday < start:
                    candidates.append((monday, folder == "plans", p))
    return max(candidates)[2].read_text() if candidates else ""


# --- the model's part ------------------------------------------------------------------

SYSTEM = """You plan one week of training for PJ. Code has already decided the week number,
whether it is a deload, and every lift's load; you choose and place the sessions and write
them up, following goals.md.

Return only JSON, no prose around it:
{
  "glance": "one sentence: the week at a glance",
  "days": [
    {"date": "YYYY-MM-DD", "rest": false, "slot": ["HH:MM", "HH:MM"],
     "type": "lift | run | bike | bag | lift+bag | lift+bike | active recovery",
     "outdoor": false, "title": "Strength A (upper)",
     "items": [{"exercise": "Bench Press (Barbell)", "sets": 4, "reps": 5, "load_lb": 165},
               {"text": "Bag 6x3 min / 1 min rest: ..."}],
     "why": "one line: purpose, or what changed from last week"}
  ],
  "summary": {"total_minutes": 0, "split": "...", "progressed": "...", "cue": "..."}
}

Rules:
- Every date listed under free windows, in order, and no others. Exactly the number of
  training days the first line asks for ("rest": false); the rest are rest days.
- Each training day's slot lies inside one of that day's free windows.
- "outdoor": true only for a run, and its slot inside that day's outdoor windows.
- A lift in the progression table uses its load_lb and reps exactly; you choose sets.
  Lifts not in the table: name them as Strong does, load_lb null, cue RPE or RIR.
- Rest days: "rest": true, "slot": null, "items": [].
- No safety disclaimer; the page adds its own.
"""


def prompt(
    start,
    number,
    is_deload,
    why,
    ctx,
    table,
    weeks,
    goals,
    previous,
    train=TRAINING_DAYS,
    from_date=None,
):
    replan = (
        f" Replanning from {from_date}: PJ has trained {TRAINING_DAYS - train} days this week"
        f" already, so plan exactly {train} training days across the dates listed below."
        if from_date
        else f" Plan exactly {train} training days."
    )
    return "\n\n".join(
        [
            f"Week {number} ({start} to {start + timedelta(days=6)}). "
            + (f"DELOAD: {why}." if is_deload else "Not a deload.")
            + replan,
            "goals.md:\n" + goals,
            "Free windows and weather per day:\n" + json.dumps(ctx["days"], indent=1),
            "Progression table (lb; dumbbell loads are per hand, as Strong logs them):\n"
            + json.dumps(table, indent=1),
            "Recent weeks (from Strong and Health):\n" + json.dumps(weeks, default=str, indent=1),
            "Last plan:\n" + (previous or "(none)"),
        ]
    )


def parse(text):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("no JSON object in the reply")
    return json.loads(m.group(0))


def _inside(slot, windows):
    s0, s1 = (_minutes(x) for x in slot)
    return any(_minutes(a) <= s0 and s1 <= _minutes(b) for a, b in windows)


def check(plan, ctx, table, train=TRAINING_DAYS):
    """Failures, as sentences the model can act on. Empty means the plan passes."""
    fails = []
    days = {d["date"]: d for d in ctx["days"]}
    got = plan.get("days", [])
    if sorted(d.get("date") for d in got) != sorted(days):
        fails.append(f"days must be exactly {', '.join(sorted(days))}")
    training = [d for d in got if not d.get("rest")]
    if len(training) != train:
        fails.append(f"{len(training)} training days; must be exactly {train}")
    loads = {r["exercise"]: r for r in table}
    for d in training:
        day = days.get(d.get("date"))
        if day is None:
            continue
        slot = d.get("slot") or []
        if len(slot) != 2 or not _inside(slot, day["free"]):
            fails.append(f"{d['date']}: slot {slot} is not inside a free window {day['free']}")
        if d.get("outdoor"):
            ok = (day.get("weather") or {}).get("outdoor_windows")
            if ok is None:
                pass  # no forecast yet for that day; nothing to check against
            elif len(slot) != 2 or not _inside(slot, ok):
                fails.append(f"{d['date']}: outdoor run at {slot}, outdoor hours are {ok}")
        for item in d.get("items", []):
            row = loads.get(item.get("exercise"))
            if row and row["load_lb"] is not None and item.get("load_lb") != row["load_lb"]:
                fails.append(
                    f"{d['date']}: {item['exercise']} at {item.get('load_lb')} lb; "
                    f"the table says {row['load_lb']}"
                )
            if row and item.get("reps") != row["reps"]:
                fails.append(
                    f"{d['date']}: {item['exercise']} for {item.get('reps')} reps; "
                    f"the table says {row['reps']}"
                )
    return fails


# --- output ----------------------------------------------------------------------------


def _item(i):
    if "text" in i:
        return i["text"]
    load = f" @ {i['load_lb']} lb" if i.get("load_lb") else ""
    return f"{i['exercise']} {i.get('sets', '?')}x{i.get('reps', '?')}{load}"


def render(plan, start, number, is_deload, why, fails, from_date=None):
    year, wk, _ = start.isocalendar()
    head = f"# Week {number} ({year}-W{wk:02d}, {start:%b %-d}–{start + timedelta(days=6):%b %-d})"
    lines = [head, "", plan.get("glance", ""), ""]
    if from_date:
        lines += [f"_Updated: replanned from {from_date:%a %b %-d}._", ""]
    lines.append(f"**Deload:** {why}." if is_deload else "Not a deload week.")
    lines.append("")
    for d in sorted(plan.get("days", []), key=lambda d: d.get("date", "")):
        day = date.fromisoformat(d["date"])
        if d.get("rest"):
            lines.append(f"**{day:%a %b %-d}**: rest. {d.get('why', '')}".rstrip())
        else:
            slot = "–".join(d.get("slot") or [])
            title = d.get("title") or d.get("type", "")
            where = " (outdoor)" if d.get("outdoor") and "outdoor" not in title.lower() else ""
            lines.append(f"**{day:%a %b %-d}, {slot}**: {title}{where}")
            lines += [f"- {_item(i)}" for i in d.get("items", [])]
            if d.get("why"):
                lines.append(f"- _{d['why']}_")
        lines.append("")
    s = plan.get("summary", {})
    lines += [
        f"**Week:** {s.get('total_minutes', '?')} min; {s.get('split', '')}",
        f"**Progressed:** {s.get('progressed', '')}",
        f"**Cue:** {s.get('cue', '')}",
        "",
        "Scale back if anything hurts. General fitness guidance, not medical advice.",
    ]
    if fails:
        lines += ["", "## Checks that failed", *[f"- {f}" for f in fails]]
    return "\n".join(lines) + "\n"


def run(week=None, brain=None, var=None, db=None, ctx=None, from_date=None):
    """Plan one week (or its days from `from_date`) and write it. Returns (path, failures)."""
    start = week_context.week_start(week)
    goals = (home(var) / "goals.md").read_text()
    number = week_number(start, goals)
    lifts, weeks = read_marts(db)
    ratio = next((w["acute_chronic_ratio"] for w in weeks if w["acute_chronic_ratio"]), None)
    is_deload, why = deload(number, ratio)
    table = progression(lifts, start, is_deload)
    if ctx is None:
        _, ctx = week_context.run(week)
    ctx = with_assumed_work(ctx, ASSUME_WORK)
    year, wk, _ = start.isocalendar()
    out = home(var) / "plans" / f"{year}-W{wk:02d}.md"
    train, earlier = TRAINING_DAYS, []
    if from_date and from_date > start:
        ctx = {**ctx, "days": [d for d in ctx["days"] if d["date"] >= from_date.isoformat()]}
        train = max(0, min(len(ctx["days"]), TRAINING_DAYS - done_days(start, from_date, db)))
        if out.with_suffix(".json").exists():
            old = json.loads(out.with_suffix(".json").read_text())
            earlier = [d for d in old.get("days", []) if d.get("date", "") < from_date.isoformat()]
    else:
        from_date = None
    previous = out.read_text() if from_date and out.exists() else last_plan(start, var)
    user = prompt(
        start, number, is_deload, why, ctx, table, weeks, goals, previous, train, from_date
    )
    if brain is None:
        from light_labs.core.brain import brain_for

        brain = brain_for(MODEL, source=SOURCE, timeout=600)
    plan, fails = None, []
    for attempt in range(2):
        ask = (
            user
            if attempt == 0
            else user + "\n\nYour last plan failed these checks; fix them:\n- " + "\n- ".join(fails)
        )
        try:
            plan = parse(brain.think(SYSTEM, ask))
        except (ValueError, json.JSONDecodeError) as e:
            fails = [f"reply was not the JSON asked for: {e}"]
            continue
        fails = check(plan, ctx, table, train)
        if not fails:
            break
    if plan is None:
        raise RuntimeError(f"no usable plan: {fails[0]}")
    plan = {**plan, "days": earlier + plan.get("days", [])}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(plan, start, number, is_deload, why, fails, from_date))
    (out.with_suffix(".json")).write_text(json.dumps(plan, indent=2) + "\n")
    return out, fails
