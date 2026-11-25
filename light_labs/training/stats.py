"""The training marts as a page in the Workouts app (`/stats`) and as Markdown
(`lab training export`, for a viewer outside the lab).

Sessions done against the plan, load, lift progress, and what was ticked in the app, from
var/lab.duckdb. Strong and Health are the record of what was trained; check-offs are shown
beside it. The marts carry numbers and exercise names only, never a note's text.

Reads read-only, one connection per page, so Dagster's writes are never held up for longer
than a query. The marts are as fresh as Dagster's last run: check-offs land twenty minutes
after the last tap, so the page says when the database was last written.
"""

import html
from datetime import datetime
from pathlib import Path

from light_labs.evals import results

WEEKS = 12
LIFTS = 15
ONLY_HERE = 10
DELOAD_ABOVE = 1.3  # plan.deload's trigger, drawn as the mark on the load bar
LOAD_SCALE = 2.0
LABEL_CLIP = 90


class Unavailable(Exception):
    """The database is busy (a write holds it) or has no training marts yet."""


def _rows(con, sql):
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def report(db=None):
    import duckdb

    path = Path(db or results.DB)
    try:
        con = duckdb.connect(str(path), read_only=True)
    except duckdb.Error as e:
        raise Unavailable(f"database busy: {e}") from e
    try:
        with con:
            weeks = _rows(
                con,
                f"""
                SELECT
                    w.week_start, w.iso_week, w.training_minutes, w.acute_chronic_ratio,
                    a.planned_sessions, a.due_sessions, a.completed_sessions,
                    a.missed_sick_or_away, a.checked_sessions, a.checked_only_sessions,
                    a.adherence_rate, u.days_used, u.checked_share, u.in_slot_share
                FROM marts.mart_training_weekly AS w
                LEFT JOIN marts.mart_training_adherence AS a ON w.week_start = a.week_start
                LEFT JOIN marts.mart_workouts_usage AS u ON w.week_start = u.week_start
                ORDER BY w.week_start DESC LIMIT {WEEKS}
                """,
            )
            lifts = _rows(
                con,
                f"""
                SELECT exercise, is_bodyweight_lift, last_session_date, top_set_weight,
                    top_set_reps, best_e1rm, e1rm_change
                FROM marts.mart_lift_progress WHERE is_latest_week
                ORDER BY last_session_date DESC, exercise LIMIT {LIFTS}
                """,
            )
            only_here = _rows(
                con,
                f"""
                SELECT plan_date, label FROM intermediate.int_training_checked_items
                WHERE NOT is_lift AND is_checked
                ORDER BY plan_date DESC, plan_item_id LIMIT {ONLY_HERE}
                """,
            )
    except duckdb.CatalogException as e:
        raise Unavailable(f"no training marts yet: run `just analytics` ({e})") from e
    built = datetime.fromtimestamp(path.stat().st_mtime)
    return {"weeks": weeks, "lifts": lifts, "only_here": only_here, "built": built}


def esc(text):
    return html.escape(str(text if text is not None else ""))


def _num(x):
    return f"{float(x):g}" if x is not None else "–"


def _pct(x):
    return f"{100 * x:.0f}%" if x is not None else "–"


def _bar(share, cls=""):
    width = max(0.0, min(1.0, share or 0)) * 100
    return f'<div class="bar"><span class="{cls}" style="width:{width:.1f}%"></span></div>'


def _tile(value, label):
    return f'<div class="tile"><b>{value}</b><span>{esc(label)}</span></div>'


def _this_week(w):
    done, planned = w["completed_sessions"], w["planned_sessions"]
    sessions = f"{done} / {planned}" if planned is not None else "–"
    return (
        '<div class="tiles">'
        + _tile(sessions, "sessions logged")
        + _tile(_num(w["checked_sessions"]), "ticked here")
        + _tile(f"{w['training_minutes'] or 0:.0f}", "minutes")
        + "</div>"
    )


def _load(w):
    ratio = w["acute_chronic_ratio"]
    if ratio is None:
        return '<p class="meta">No load yet: nothing logged in the last four weeks.</p>'
    ratio = float(ratio)
    mark = 100 * DELOAD_ABOVE / LOAD_SCALE
    over = ratio > DELOAD_ABOVE
    return (
        f'<div class="load"><b class="{"warn" if over else ""}">{ratio:.2f}</b>'
        f'<div class="bar"><span class="{"warn" if over else ""}" '
        f'style="width:{min(ratio / LOAD_SCALE, 1) * 100:.1f}%"></span>'
        f'<i style="left:{mark:.0f}%"></i></div></div>'
        f'<p class="meta">This week against the four-week average. Above {DELOAD_ABOVE} '
        "the next plan deloads.</p>"
    )


def _week_row(w):
    planned = w["planned_sessions"] is not None
    count = f"{w['completed_sessions']}/{w['due_sessions']}" if planned else "no plan"
    notes = [f"{w['training_minutes'] or 0:.0f} min"]
    if w["missed_sick_or_away"]:
        notes.append(f"{w['missed_sick_or_away']} missed sick or away")
    if w["days_used"]:
        notes.append(f"ticked {_pct(w['checked_share'])}, {_pct(w['in_slot_share'])} in the slot")
    if w["checked_only_sessions"]:
        notes.append(f"{w['checked_only_sessions']} ticked only")
    return (
        f'<div class="wk"><span>{esc(w["iso_week"][5:])}</span>{_bar(w["adherence_rate"], "on")}'
        f'<span>{count}</span><span class="meta">{esc(" · ".join(notes))}</span></div>'
    )


def _lift_row(lift):
    if lift["is_bodyweight_lift"] and not lift["top_set_weight"]:
        top = f"bodyweight × {_num(lift['top_set_reps'])}"
    else:
        top = f"{_num(lift['top_set_weight'])} lb × {_num(lift['top_set_reps'])}"
    change = lift["e1rm_change"]
    if lift["best_e1rm"] is None:
        e1rm = ""
    else:
        moved = f" ({change:+.1f})" if change else ""
        cls = "up" if (change or 0) > 0 else "down" if (change or 0) < 0 else ""
        e1rm = f'e1RM {lift["best_e1rm"]:.0f}<span class="{cls}">{moved}</span> · '
    when = f"{lift['last_session_date']:%b} {lift['last_session_date'].day}"
    return (
        f'<div class="lift"><div>{esc(lift["exercise"])}</div>'
        f'<div class="meta">{esc(top)} · {e1rm}{when}</div></div>'
    )


def render(rep):
    """The page's body."""
    weeks = rep["weeks"]
    if not weeks:
        return '<p class="meta">Nothing logged yet.</p>'
    out = [
        "<h2>This week</h2>",
        _this_week(weeks[0]),
        "<h2>Load</h2>",
        _load(weeks[0]),
        f"<h2>Last {len(weeks)} weeks</h2>",
        '<p class="meta">Sessions logged in Strong or Health against sessions due.</p>',
        "".join(_week_row(w) for w in weeks),
    ]
    if rep["lifts"]:
        out += ["<h2>Lifts</h2>", "".join(_lift_row(x) for x in rep["lifts"])]
    if rep["only_here"]:
        out += [
            "<h2>Only recorded here</h2>",
            '<p class="meta">Ticked items no other app captures.</p>',
            "".join(
                f'<div class="lift"><div>{esc(r["label"][:LABEL_CLIP])}</div>'
                f'<div class="meta">{r["plan_date"]:%a %b} {r["plan_date"].day}</div></div>'
                for r in rep["only_here"]
            ),
        ]
    built = rep["built"]
    out.append(
        f'<p class="meta built">Data as of {built:%a %b} {built.day}, {built:%H:%M}. '
        "Ticks show here about twenty minutes after the last one.</p>"
    )
    return "".join(out)


def _cell(text):
    """Table-cell text: an exercise name can't end the cell or start markup."""
    return str(text).replace("\\", "\\\\").replace("|", "\\|").replace("<", "&lt;")


def markdown(rep):
    """The same report as `render`, as a Markdown page."""
    weeks = rep["weeks"]
    out = ["# Training progress", ""]
    if not weeks:
        return "\n".join(out + ["Nothing logged yet.", ""])
    w = weeks[0]
    done, planned = w["completed_sessions"], w["planned_sessions"]
    ratio = w["acute_chronic_ratio"]
    if ratio is None:
        load = "none yet (nothing logged in the last four weeks)"
    else:
        over = float(ratio) > DELOAD_ABOVE
        load = f"{float(ratio):.2f}" + (
            f", above {DELOAD_ABOVE}: the next plan deloads" if over else ""
        )
    sessions = f"{done} / {planned}" if planned is not None else "–"
    this_week = (
        f"| {sessions} | {_num(w['checked_sessions'])} "
        f"| {w['training_minutes'] or 0:.0f} | {load} |"
    )
    out += [
        f"## This week ({w['iso_week']})",
        "",
        "| Sessions logged | Ticked in Workouts | Minutes | Load vs four-week average |",
        "|---|---|---|---|",
        this_week,
        "",
        f"## Last {len(weeks)} weeks",
        "",
        "Sessions logged in Strong or Health against sessions due.",
        "",
        "| Week | Logged / due | Adherence | Minutes | Notes |",
        "|---|---|---:|---:|---|",
    ]
    for w in weeks:
        has_plan = w["planned_sessions"] is not None
        notes = []
        if w["missed_sick_or_away"]:
            notes.append(f"{w['missed_sick_or_away']} missed sick or away")
        if w["days_used"]:
            notes.append(
                f"ticked {_pct(w['checked_share'])}, {_pct(w['in_slot_share'])} in the slot"
            )
        if w["checked_only_sessions"]:
            notes.append(f"{w['checked_only_sessions']} ticked only")
        out.append(
            f"| {w['iso_week'][5:]} "
            f"| {f'{w["completed_sessions"]}/{w["due_sessions"]}' if has_plan else 'no plan'} "
            f"| {_pct(w['adherence_rate']) if has_plan else ''} "
            f"| {w['training_minutes'] or 0:.0f} | {', '.join(notes)} |"
        )
    if rep["lifts"]:
        out += [
            "",
            "## Lifts",
            "",
            "| Lift | Top set | e1RM | Change | Last |",
            "|---|---|---:|---:|---|",
        ]
        for lift in rep["lifts"]:
            if lift["is_bodyweight_lift"] and not lift["top_set_weight"]:
                top = f"bodyweight × {_num(lift['top_set_reps'])}"
            else:
                top = f"{_num(lift['top_set_weight'])} lb × {_num(lift['top_set_reps'])}"
            best, change = lift["best_e1rm"], lift["e1rm_change"]
            when = f"{lift['last_session_date']:%b} {lift['last_session_date'].day}"
            out.append(
                f"| {_cell(lift['exercise'])} | {top} | {'' if best is None else f'{best:.0f}'} "
                f"| {f'{change:+.1f}' if change else ''} | {when} |"
            )
    if rep["only_here"]:
        out += ["", "## Only recorded in Workouts", "", "| Item | Day |", "|---|---|"]
        out += [
            f"| {_cell(r['label'][:LABEL_CLIP])} | {r['plan_date']:%a %b} {r['plan_date'].day} |"
            for r in rep["only_here"]
        ]
    built = rep["built"]
    out += ["", f"Data as of {built:%a %b} {built.day}, {built:%H:%M}.", ""]
    return "\n".join(out)
