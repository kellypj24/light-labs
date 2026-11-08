"""Circles: PJ's circles.yaml, and the bootstrap proposal from interaction history."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb
import yaml

from light_labs.radar import normalize
from light_labs.radar.metrics import PersonMetrics

log = logging.getLogger("radar")

DEFAULT_CADENCE: dict[str, int | None] = {
    "inner": 14,
    "close": 30,
    "friends": 90,
    "network": 182,
    "dormant": None,
}


@dataclass(frozen=True)
class Assignment:
    circle: str
    cadence_days: int | None


def load(con: duckdb.DuckDBPyConnection, path: Path, region: str = "US") -> dict[str, Assignment]:
    """person_id -> assignment. Also mirrors the rules into `cadence_rules`."""
    raw = (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}
    cadence = dict(DEFAULT_CADENCE)
    cadence.update(raw.get("circles") or {})
    by_name: dict[str, list[str]] = {}
    for pid, name in con.execute("SELECT person_id, display_name FROM people").fetchall():
        by_name.setdefault(normalize.name(name), []).append(pid)

    out: dict[str, Assignment] = {}
    for key, spec in (raw.get("people") or {}).items():
        circle = spec if isinstance(spec, str) else spec.get("circle")
        if circle not in cadence:
            log.warning("circles.yaml: %r has unknown circle %r", key, circle)
            continue
        days = spec.get("cadence_days") if isinstance(spec, dict) else None
        days = days if days is not None else cadence[circle]
        for pid in _people_for(con, str(key), by_name, region):
            out[pid] = Assignment(circle, days)

    con.execute("DELETE FROM cadence_rules")
    con.executemany(
        "INSERT INTO cadence_rules VALUES ('circle', ?, ?, ?)",
        [(c, c, d) for c, d in cadence.items()],
    )
    if out:
        con.executemany(
            "INSERT INTO cadence_rules VALUES ('person', ?, ?, ?)",
            [(pid, a.circle, a.cadence_days) for pid, a in out.items()],
        )
    return out


def _people_for(
    con: duckdb.DuckDBPyConnection, key: str, by_name: dict[str, list[str]], region: str
) -> list[str]:
    ref = normalize.identity_ref(key, region)
    if key.startswith("p_"):
        rows = con.execute("SELECT person_id FROM people WHERE person_id = ?", [key]).fetchall()
        pids = [r[0] for r in rows]
    elif ref:
        rows = con.execute(
            "SELECT person_id FROM identities WHERE kind = ? AND value_norm = ?", list(ref)
        ).fetchall()
        pids = [r[0] for r in rows]
    else:
        pids = by_name.get(normalize.name(key), [])
    if not pids:
        log.warning("circles.yaml: no person matches %r", key)
    elif len(pids) > 1:
        log.warning("circles.yaml: %r matches %d people; use a phone or email", key, len(pids))
    return pids


def propose(m: PersonMetrics) -> tuple[str, str]:
    """Circle and the evidence for it, from 30-day buckets over the last two years."""
    last12, last24 = m.active_in(0, 11), m.active_in(0, 23)
    why = f"active {last12}/12 months, {last24}/24"
    if m.last_two_way:
        why += f", last two-way {m.last_two_way.isoformat()}"
    if last12 >= 10 and m.active_in(0, 1) >= 1:
        return "inner", why
    if last12 >= 6 and m.active_in(0, 2) >= 1:
        return "close", why
    if last24 >= 3 and last12 >= 1:
        return "friends", why
    if last24 >= 1:
        return "network", why
    return "dormant", why


def write_proposal(path: Path, metrics: list[PersonMetrics], as_of: datetime) -> dict[str, int]:
    """circles.proposed.yaml: same shape as circles.yaml, one comment of evidence per person.
    Dormant people are counted, not listed."""
    proposals = [(m, *propose(m)) for m in metrics]
    counts: dict[str, int] = {c: 0 for c in DEFAULT_CADENCE}
    for _, circle, _ in proposals:
        counts[circle] += 1
    names = [m.display_name for m, c, _ in proposals if c != "dormant"]
    dupes = {n for n in names if names.count(n) > 1}

    lines = [
        f"# Proposed by `lab radar bootstrap` on {as_of.date().isoformat()}. Review, edit, then",
        "# copy what you agree with into circles.yaml. Nothing here is applied.",
        f"# Not listed: {counts['dormant']} dormant (no active month in two years).",
        "circles:",
        *(f"  {c}: {'null' if d is None else d}" for c, d in DEFAULT_CADENCE.items()),
        "people:",
    ]
    order = list(DEFAULT_CADENCE)
    for m, circle, why in sorted(proposals, key=lambda p: (order.index(p[1]), p[0].display_name)):
        if circle == "dormant":
            continue
        key = m.display_name if m.display_name not in dupes else m.person_id
        lines.append(f"  {json.dumps(key, ensure_ascii=False)}: {circle}  # {why}")
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)
    return counts
