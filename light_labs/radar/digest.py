"""The weekly digest. Self-contained Markdown: the cloud task reads it with no other context.

Snippets appear only in the local dated copy, and only with --with-snippets; the shared
copy (Drive) never carries message text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import duckdb

from light_labs.radar.circles import Assignment
from light_labs.radar.metrics import PersonMetrics

TOP_N = 5
BIRTHDAY_DAYS = 14
SILENCE_DAYS = 60


@dataclass(frozen=True)
class Pick:
    m: PersonMetrics
    circle: str | None
    days_since: int | None
    overdue: float
    reason: str
    kind: str  # birthday | silence | overdue | never


def next_birthday(bday: date, today: date) -> date:
    for year in (today.year, today.year + 1):
        try:
            d = bday.replace(year=year)
        except ValueError:  # Feb 29 in a non-leap year
            d = date(year, 3, 1)
        if d >= today:
            return d
    raise AssertionError("unreachable")


def first_name(m: PersonMetrics) -> str:
    n = m.display_name
    return n.split()[0] if n and not n.startswith("+") and "@" not in n else "there"


def opener(p: Pick, today: date) -> str:
    f = first_name(p.m)
    if p.kind == "birthday" and p.m.birthday:
        when = next_birthday(p.m.birthday, today).strftime("%A")
        return f"Hey {f}, your birthday's coming up {when}. Let's get something on the calendar."
    if p.kind == "silence" and p.m.last_contact:
        month = p.m.last_contact.strftime("%B")
        return f"Hey {f}, realized we haven't talked since {month}. What's new with you?"
    if p.kind == "network":
        at = f" at {p.m.org}" if p.m.org else ""
        return f"Hey {f}, been a while. Curious what you're working on{at} these days. Coffee soon?"
    return f"Hey {f}, been too long. How are things?"


def _days_since(m: PersonMetrics, as_of: datetime) -> int | None:
    return (as_of - m.last_contact).days if m.last_contact else None


def picks(
    metrics: list[PersonMetrics], circles: dict[str, Assignment], as_of: datetime
) -> list[Pick]:
    today = as_of.date()
    out = []
    for m in metrics:
        a = circles.get(m.person_id)
        if not a or not a.cadence_days:
            continue
        days = _days_since(m, as_of)
        overdue = (days / a.cadence_days) if days is not None else 99.0
        bday_in = (next_birthday(m.birthday, today) - today).days if m.birthday else None
        prior_active = m.active_in(3, 14)
        if bday_in is not None and bday_in <= BIRTHDAY_DAYS:
            kind, reason = "birthday", f"birthday in {bday_in} days"
        elif days is not None and days >= SILENCE_DAYS and prior_active >= 3:
            kind = "silence"
            reason = f"quiet {days} days after {prior_active} active months"
        elif days is None:
            kind, reason = "never", "no contact on record"
        elif overdue >= 1:
            kind, reason = "overdue", f"{overdue:.1f}x past your {a.cadence_days}-day cadence"
        else:
            continue
        boost = {"birthday": 2.0, "silence": 1.0}.get(kind, 0.0)
        out.append(Pick(m, a.circle, days, overdue + boost, reason, kind))
    out.sort(key=lambda p: (-p.overdue, p.m.display_name))
    return out


def network_picks(
    metrics: list[PersonMetrics],
    circles: dict[str, Assignment],
    former_employers: list[str],
    as_of: datetime,
    exclude: set[str],
    n: int = 2,
) -> list[Pick]:
    """Former colleagues first (company matches a configured employer), then `network`."""
    employers = [e.lower() for e in former_employers]
    cands = []
    for m in metrics:
        if m.person_id in exclude:
            continue
        a = circles.get(m.person_id)
        colleague = bool(m.org) and any(e in m.org.lower() for e in employers)
        if not colleague and not (a and a.circle == "network"):
            continue
        if a and a.circle == "dormant":
            continue
        days = _days_since(m, as_of)
        if days is not None and days < 90:
            continue
        cands.append(Pick(m, a.circle if a else None, days, days or 9999, "", "network"))
    cands.sort(
        key=lambda p: (
            not (p.m.org and any(e in p.m.org.lower() for e in employers)),
            -p.overdue,
            p.m.display_name,
        )
    )
    return cands[:n]


def _last(p: Pick) -> str:
    if p.days_since is None:
        return "Last contact: none on record."
    via = f" via {p.m.last_channel}" if p.m.last_channel else ""
    return f"Last contact: {p.days_since} days ago{via}."


def _stats(con: duckdb.DuckDBPyConnection, circles: dict[str, Assignment], as_of: datetime) -> str:
    this_month = as_of.date().replace(day=1)
    last_month = (this_month - timedelta(days=1)).replace(day=1)
    rows = con.execute(
        """
        SELECT person_id,
               count(*) FILTER (WHERE ts >= $this AND ts <= $as_of),
               count(*) FILTER (WHERE ts >= $last AND ts < $this)
        FROM person_interactions GROUP BY person_id
        """,
        {"this": this_month, "last": last_month, "as_of": as_of},
    ).fetchall()
    by_circle: dict[str, list[int]] = {}
    for pid, now, prev in rows:
        c = circles[pid].circle if pid in circles else "unassigned"
        acc = by_circle.setdefault(c, [0, 0])
        acc[0] += now
        acc[1] += prev
    order = ["inner", "close", "friends", "network", "dormant", "unassigned"]
    lines = [
        f"| Circle | {this_month:%b} (to date) | {last_month:%b} |",
        "|---|---:|---:|",
    ]
    for c in sorted(by_circle, key=lambda c: order.index(c) if c in order else 99):
        lines.append(f"| {c} | {by_circle[c][0]} | {by_circle[c][1]} |")
    return "\n".join(lines)


def render(
    con: duckdb.DuckDBPyConnection,
    metrics: list[PersonMetrics],
    circles: dict[str, Assignment],
    former_employers: list[str],
    as_of: datetime,
    snippets: dict[str, str] | None = None,
) -> str:
    today = as_of.date()
    top = picks(metrics, circles, as_of)[:TOP_N]
    out = [
        f"# Relationship Radar: week of {today.isoformat()}",
        "",
        "Generated locally from message and contact metadata. Counts and dates only; "
        "no message content" + (" except the snippets marked below." if snippets else "."),
        "",
        "## Reach out this week",
        "",
    ]
    if not top:
        out.append(
            "Nobody is past their cadence. Assign circles in circles.yaml if this looks wrong."
        )
    for i, p in enumerate(top, 1):
        out += [
            f"{i}. **{p.m.display_name}** ({p.circle}): {p.reason}.",
            f"   {_last(p)}",
            f'   Opener: "{opener(p, today)}"',
        ]
        if snippets and p.m.person_id in snippets:
            out.append(f'   Last message (snippet): "{snippets[p.m.person_id]}"')

    out += ["", f"## Birthdays, next {BIRTHDAY_DAYS} days", ""]
    bdays = sorted(
        ((next_birthday(m.birthday, today), m) for m in metrics if m.birthday),
        key=lambda x: (x[0], x[1].display_name),
    )
    bdays = [(d, m) for d, m in bdays if (d - today).days <= BIRTHDAY_DAYS]
    if not bdays:
        out.append("None.")
    for d, m in bdays:
        age = ""
        if m.birthday_has_year and m.birthday:
            age = f", turns {d.year - m.birthday.year}"
        out.append(f"- {d:%a %b} {d.day}: {m.display_name}{age}")

    out += ["", "## Professional network", ""]
    net = network_picks(metrics, circles, former_employers, as_of, {p.m.person_id for p in top})
    if not net:
        out.append("No one to suggest yet (needs org data or a `network` circle).")
    for p in net:
        role = ", ".join(x for x in (p.m.title, p.m.org) if x) or "no role on record"
        out += [
            f"- **{p.m.display_name}** ({role}). {_last(p)}",
            f'  Opener: "{opener(p, today)}"',
        ]

    out += ["", "## Cooling", ""]
    cooling = [
        m
        for m in metrics
        if m.trend == "cooling"
        and m.person_id in circles
        and circles[m.person_id].circle not in ("dormant",)
    ]
    if not cooling:
        out.append("Nobody in your circles is cooling.")
    for m in sorted(cooling, key=lambda m: m.n_90d - m.n_prev_90d)[:10]:
        out.append(
            f"- {m.display_name} ({circles[m.person_id].circle}): "
            f"{m.n_90d} interactions in the last 90 days, {m.n_prev_90d} the 90 before"
        )

    out += ["", "## Stats", "", _stats(con, circles, as_of), ""]
    return "\n".join(out)


def latest_snippets(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    rows = con.execute(
        """
        SELECT person_id, arg_max(snippet, ts) FROM person_interactions
        WHERE snippet IS NOT NULL GROUP BY person_id
        """
    ).fetchall()
    return {pid: s.replace("\n", " ") for pid, s in rows}
