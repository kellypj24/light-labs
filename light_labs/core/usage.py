"""Claude Code's usage over the whole history in var/lab.duckdb, as a phone page.

What the marts say Claude spends its time and tokens on, week by week and project by
project, to pick what to take off it: deterministic work for a script or harness,
small-model work for a robot. Claude Code's own /stats covers only the sessions it still
keeps; this covers everything `lab claude ingest` has landed.

Reads the marts read-only, one connection per page, so Dagster's writes are never held
up for longer than a query.
"""

import html

from light_labs.evals import results

# visual-recap's activity colors, so the strips read the same as its band.
ACTIVITY = [
    ("thinking", "Thinking", "#D97757"),
    ("reading", "Reading", "#5B9BD5"),
    ("editing", "Editing", "#6BBF59"),
    ("shell", "Shell", "#C678DD"),
    ("web", "Web", "#4FB6C2"),
    ("subagent", "Subagents", "#E5C07B"),
    ("asking", "Asking you", "#E06C75"),
    ("other_tool", "Other tools", "#9DA5B4"),
]
WEEKS = 26
TOP_WORK = 12


class Unavailable(Exception):
    """The database is busy (a write holds it) or has no Claude marts yet."""


def _rows(con, sql):
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def report(db=None):
    import duckdb

    try:
        con = duckdb.connect(str(db or results.DB), read_only=True)
    except duckdb.Error as e:
        raise Unavailable(f"database busy: {e}") from e
    seconds = ", ".join(f"SUM({key}_seconds) AS {key}" for key, _, _ in ACTIVITY)
    try:
        with con:
            weeks = _rows(
                con,
                f"""
                WITH activity AS (
                    SELECT week_start, SUM(turn_count) AS turns,
                        SUM(working_seconds) AS working, {seconds}
                    FROM marts.mart_claude_activity_weekly GROUP BY week_start
                ), tasks AS (
                    SELECT week_start,
                        SUM(context_tokens) FILTER (WHERE is_deterministic) AS det_tokens,
                        SUM(context_tokens) AS tokens
                    FROM marts.mart_claude_task_weekly GROUP BY week_start
                )
                SELECT activity.*, tasks.det_tokens, tasks.tokens
                FROM activity LEFT JOIN tasks USING (week_start)
                ORDER BY week_start DESC LIMIT {WEEKS}
                """,
            )
            projects = _rows(
                con,
                f"""
                SELECT project, worktree, SUM(working_seconds) AS working,
                    SUM(turn_count) AS turns, {seconds}
                FROM marts.mart_claude_activity_weekly
                GROUP BY project, worktree ORDER BY working DESC
                """,
            )
            tasks = _rows(
                con,
                """
                SELECT task_type, BOOL_OR(is_deterministic) AS deterministic,
                    SUM(call_count) AS calls, SUM(error_count) AS errors,
                    SUM(total_seconds) AS seconds, SUM(context_tokens) AS tokens
                FROM marts.mart_claude_task_weekly
                GROUP BY task_type ORDER BY tokens DESC NULLS LAST
                """,
            )
            work = _rows(
                con,
                f"""
                SELECT pattern, task_type, call_count AS calls, session_count AS sessions,
                    project_count AS projects, total_seconds AS seconds,
                    context_tokens AS tokens
                FROM marts.mart_claude_repeated_work
                WHERE task_type IN
                    ('git', 'github', 'checks', 'wait', 'network', 'files', 'services')
                ORDER BY context_tokens DESC NULLS LAST LIMIT {TOP_WORK}
                """,
            )
            span = con.execute(
                "SELECT CAST(MIN(started_at) AS DATE), CAST(MAX(ended_at) AS DATE), COUNT(*), "
                "SUM(prompt_count) "
                "FROM marts.mart_claude_sessions"
            ).fetchone()
    except duckdb.CatalogException as e:
        raise Unavailable(f"no Claude marts yet: run `just analytics` ({e})") from e
    return {"weeks": weeks, "projects": projects, "tasks": tasks, "work": work, "span": span}


def _hours(seconds):
    return f"{(seconds or 0) / 3600:.1f}h"


def _tokens(n):
    n = n or 0
    return f"{n / 1e6:.0f}M" if n >= 1e6 else f"{n / 1e3:.0f}k"


def _n(n, word):
    return f"{n or 0} {word}" + ("" if n == 1 else "s")


def _turns(n):
    return _n(n, "turn")


def _pct(part, whole):
    return f"{100 * (part or 0) / whole:.0f}%" if whole else "–"


def _bar(value, scale, color):
    width = 100 * (value or 0) / scale if scale else 0
    return f'<div class="strip"><span style="width:{width:.2f}%;background:{color}"></span></div>'


def _row(name, bar, value, meta, cls="name"):
    return (
        f'<div class="week"><span class="{cls}">{name}</span>{bar}<span>{value}</span>'
        f'<span class="meta">{meta}</span></div>'
    )


def _strip(row, scale):
    """A bar as long as the row's working time against `scale`, cut by activity."""
    if not scale or not row.get("working"):
        return '<div class="strip"></div>'
    cells = "".join(
        f'<span style="width:{100 * (row[key] or 0) / scale:.2f}%;background:{color}" '
        f'title="{label} {_hours(row[key])}"></span>'
        for key, label, color in ACTIVITY
        if row.get(key)
    )
    return f'<div class="strip">{cells}</div>'


def render(rep):
    weeks, projects, tasks, work = rep["weeks"], rep["projects"], rep["tasks"], rep["work"]
    first, last, sessions, prompts = rep["span"]
    total = sum(w["working"] or 0 for w in weeks)
    all_tokens = sum(t["tokens"] or 0 for t in tasks)
    det_tokens = sum(t["tokens"] or 0 for t in tasks if t["deterministic"])
    det_seconds = sum(t["seconds"] or 0 for t in tasks if t["deterministic"])
    out = [
        f'<p class="meta">{first:%Y-%m-%d} to {last:%Y-%m-%d} · {_n(sessions, "session")} · '
        f"{_n(prompts, 'prompt')}</p>"
        if first
        else '<p class="meta">No sessions yet.</p>',
        (
            f"<p><b>{_hours(total)}</b> working over {_n(len(weeks), 'week')}. "
            f"<b>{_pct(det_tokens, all_tokens)}</b> of the tokens Claude spent on tool calls, "
            f"and {_hours(det_seconds)}, went to deterministic work a script or harness "
            "could take over.</p>"
        ),
        '<div class="legend">'
        + "".join(
            f'<span><i style="background:{color}"></i>{label}</span>'
            for _, label, color in ACTIVITY
        )
        + "</div>",
        "<h2>By week</h2>",
    ]
    top = max((w["working"] or 0 for w in weeks), default=0)
    for w in weeks:
        out.append(
            _row(
                f"{w['week_start']:%Y-%m-%d}",
                _strip(w, top),
                _hours(w["working"]),
                f"{_turns(w['turns'])} · {_pct(w['det_tokens'], w['tokens'])} deterministic",
            )
        )

    out.append("<h2>By project</h2>")
    by_project = {}
    for p in projects:
        by_project.setdefault(p["project"], []).append(p)
    totals = []
    for name, trees in by_project.items():
        row = {key: sum(t[key] or 0 for t in trees) for key, _, _ in ACTIVITY}
        row.update(
            working=sum(t["working"] or 0 for t in trees),
            turns=sum(t["turns"] or 0 for t in trees),
        )
        totals.append((name, row, trees))
    totals.sort(key=lambda item: -item[1]["working"])
    widest = max((row["working"] for _, row, _ in totals), default=0)
    for name, row, trees in totals:
        line = _row(
            html.escape(name or "?"),
            _strip(row, widest),
            _hours(row["working"]),
            f"{_turns(row['turns'])} · {_pct(row['working'], total)} of working time",
        )
        named = [t for t in trees if t["worktree"] and t["worktree"] != name]
        if not named:
            out.append(line)
            continue
        rows = "".join(
            _row(
                html.escape(t["worktree"] or "–"),
                _strip(t, widest),
                _hours(t["working"]),
                _turns(t["turns"]),
                cls="name meta",
            )
            for t in trees
        )
        out.append(f"<details><summary>{line}</summary>{rows}</details>")

    out.append(
        "<h2>What tool calls did</h2>"
        '<p class="meta">Tokens Claude spent deciding on each kind of call; '
        '<span style="color:var(--warn)">orange</span> is deterministic work.</p>'
    )
    most = max((t["tokens"] or 0 for t in tasks), default=0)
    for t in tasks:
        color = "var(--warn)" if t["deterministic"] else "var(--muted)"
        out.append(
            _row(
                html.escape(t["task_type"]),
                _bar(t["tokens"], most, color),
                _tokens(t["tokens"]),
                f"{_pct(t['tokens'], all_tokens)} · {_n(t['calls'], 'call')} · {_n(t['errors'], 'error')}"
                f" · {_hours(t['seconds'])}",
            )
        )

    out.append(
        "<h2>Repeated deterministic work</h2>"
        '<p class="meta">Candidates for a script, a lab command or a robot.</p>'
    )
    most = max((w["tokens"] or 0 for w in work), default=0)
    for w in work:
        out.append(
            _row(
                f"<code>{html.escape(w['pattern'])}</code>",
                _bar(w["tokens"], most, "var(--warn)"),
                _tokens(w["tokens"]),
                f"{html.escape(w['task_type'])} · {_n(w['calls'], 'call')} · {_n(w['sessions'], 'session')}"
                f" · {_n(w['projects'], 'project')} · {_hours(w['seconds'])}",
            )
        )
    return "".join(out)
