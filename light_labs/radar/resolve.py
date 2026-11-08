"""Identity resolution: rebuild `people` and `identities` from source facts and overrides.

Order: exact (a card's own phones and emails) → overrides (merge, split) → PJ's decisions
in review_matches.csv → fuzzy names. A fuzzy match merges on its own only at or above
`fuzzy_auto_merge` *and* with a second shared attribute (organization or birthday);
everything from `fuzzy_review_floor` up goes to review_matches.csv for PJ.

overrides.yaml (see examples/overrides.example.yaml) refers to people by identity
(phone, email, LinkedIn URL), by `*@domain`, or by a card's exact display name.
"""

from __future__ import annotations

import csv
import itertools
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml
from rapidfuzz import fuzz, process

from light_labs.radar import normalize
from light_labs.radar.config import Paths, Settings

SOURCE_PRIORITY = {"contacts": 0, "linkedin": 1, "gmail": 2, "calendar": 3}
REVIEW_FIELDS = ["left", "right", "left_name", "right_name", "score", "why", "decision"]


@dataclass
class Overrides:
    me: list[str] = field(default_factory=list)
    merge: list[list[str]] = field(default_factory=list)
    split: list[list[str]] = field(default_factory=list)
    ignore: list[str] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    tags: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Overrides:
        raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {} if path.exists() else {}
        return cls(
            me=[str(x) for x in raw.get("me") or []],
            merge=[[str(x) for x in g] for g in raw.get("merge") or []],
            split=[[str(x) for x in g] for g in raw.get("split") or []],
            ignore=[str(x) for x in raw.get("ignore") or []],
            names={str(k): str(v) for k, v in (raw.get("names") or {}).items()},
            tags={str(k): [str(t) for t in v] for k, v in (raw.get("tags") or {}).items()},
        )


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, x: str) -> None:
        self.parent.setdefault(x, x)

    def find(self, x: str) -> str:
        self.add(x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for x in self.parent:
            out[self.find(x)].append(x)
        return out


@dataclass
class ResolveResult:
    people: int
    review_rows: int
    auto_merged: int


def resolve(con: duckdb.DuckDBPyConnection, paths: Paths, settings: Settings) -> ResolveResult:
    ov = Overrides.load(paths.overrides)
    region = settings.default_region

    cards = {
        f"sp:{src}:{key}": {
            "source": src,
            "name": name,
            "org": org,
            "title": title,
            "birthday": bday,
            "has_year": has_year,
        }
        for src, key, name, org, title, bday, has_year in con.execute(
            "SELECT source, source_key, display_name, org, title, birthday, birthday_has_year "
            "FROM source_people"
        ).fetchall()
    }
    card_idents = con.execute(
        "SELECT source, source_key, kind, value_norm FROM source_identities"
    ).fetchall()
    seen_idents = con.execute(
        "SELECT DISTINCT identity_kind, identity_value FROM interactions"
    ).fetchall()

    def ident_node(kind: str, value: str) -> str:
        return f"id:{kind}:{value}"

    all_ident_nodes = {ident_node(k, v) for _, _, k, v in card_idents}
    all_ident_nodes |= {ident_node(k, v) for k, v in seen_idents}

    def nodes_for(ref: str) -> set[str]:
        if ref.startswith("*@"):
            domain = ref[1:].lower()
            return {n for n in all_ident_nodes if n.startswith("id:email:") and n.endswith(domain)}
        parsed = normalize.identity_ref(ref, region)
        if parsed:
            return {ident_node(*parsed)}
        folded = normalize.name(ref)
        return {n for n, c in cards.items() if c["name"] and normalize.name(c["name"]) == folded}

    me = set().union(*(nodes_for(r) for r in ov.me)) if ov.me else set()
    split_nodes = set().union(*(nodes_for(r) for g in ov.split for r in g)) if ov.split else set()
    method: dict[str, tuple[str, float]] = {}

    uf = UnionFind()
    for n in cards:
        uf.add(n)
    for n in all_ident_nodes - me:
        uf.add(n)
    for src, key, kind, value in card_idents:
        node = ident_node(kind, value)
        if node in me or node in split_nodes:
            continue
        uf.union(f"sp:{src}:{key}", node)
        method[node] = ("exact", 1.0)
    for group in ov.split + ov.merge:
        members = sorted(set().union(*(nodes_for(r) for r in group)) - me)
        for m in members:
            uf.add(m)
            method[m] = ("override", 1.0)
        for a, b in itertools.pairwise(members):
            uf.union(a, b)

    decisions = _read_decisions(paths.review_matches)
    for (a, b), d in decisions.items():
        if d == "merge" and a in cards and b in cards:
            uf.union(a, b)

    auto, review = _fuzzy(uf, cards, decisions, settings)
    for a, b, _ in auto:
        uf.union(a, b)

    ignored = set().union(*(nodes_for(r) for r in ov.ignore)) if ov.ignore else set()
    names_by_node = {n: v for ref, v in ov.names.items() for n in nodes_for(ref)}
    tags_by_node = {n: t for ref, ts in ov.tags.items() for n in nodes_for(ref) for t in ts}

    now = datetime.now(UTC)
    con.execute("DELETE FROM identities")
    con.execute("DELETE FROM people")
    con.execute("DELETE FROM tags")
    people_rows, ident_rows, tag_rows = [], [], []
    for members in uf.groups().values():
        member_cards = sorted(
            (m for m in members if m in cards),
            key=lambda m: (SOURCE_PRIORITY.get(cards[m]["source"], 9), m),
        )
        idents = sorted(m for m in members if m.startswith("id:"))
        anchor = member_cards[0] if member_cards else idents[0]
        person_id = normalize.stable_id(anchor, prefix="p_", length=12)

        def first(attr: str, cs: list[str] = member_cards) -> Any:
            return next((cards[c][attr] for c in cs if cards[c][attr] is not None), None)

        bday_card = next((c for c in member_cards if cards[c]["birthday"]), None)
        display = next((names_by_node[m] for m in members if m in names_by_node), None)
        display = display or first("name") or idents[0].split(":", 2)[2]
        people_rows.append(
            (
                person_id,
                display,
                first("org"),
                first("title"),
                cards[bday_card]["birthday"] if bday_card else None,
                cards[bday_card]["has_year"] if bday_card else None,
                any(m in ignored for m in members),
                now,
            )
        )
        for node in idents:
            _, kind, value = node.split(":", 2)
            m, conf = method.get(node, ("exact", 1.0) if member_cards else ("unmatched", 1.0))
            ident_rows.append((kind, value, person_id, m, conf))
        tag_rows += [
            (person_id, t) for t in {tags_by_node[m] for m in members if m in tags_by_node}
        ]

    if people_rows:
        con.executemany("INSERT INTO people VALUES (?, ?, ?, ?, ?, ?, ?, ?)", people_rows)
    if ident_rows:
        con.executemany("INSERT INTO identities VALUES (?, ?, ?, ?, ?)", ident_rows)
    if tag_rows:
        con.executemany("INSERT INTO tags VALUES (?, ?)", tag_rows)
    _write_review(paths.review_matches, review, cards, decisions)
    return ResolveResult(people=len(people_rows), review_rows=len(review), auto_merged=len(auto))


def _fuzzy(
    uf: UnionFind,
    cards: dict[str, dict[str, Any]],
    decisions: dict[tuple[str, str], str],
    settings: Settings,
) -> tuple[list[tuple[str, str, float]], list[tuple[str, str, float, str]]]:
    """Compare one named card per component against the others."""
    reps: dict[str, str] = {}
    for n in sorted(cards):
        if cards[n]["name"]:
            reps.setdefault(uf.find(n), n)
    nodes = list(reps.values())
    if len(nodes) < 2:
        return [], []
    names = [normalize.name(cards[n]["name"]) for n in nodes]
    floor = settings.fuzzy_review_floor * 100
    auto, review = [], []
    for i in range(len(nodes)):
        later = names[i + 1 :]
        for _, raw, k in process.extract(
            names[i], later, scorer=fuzz.token_sort_ratio, score_cutoff=floor, limit=None
        ):
            j, score = i + 1 + k, float(raw) / 100
            a, b = nodes[i], nodes[j]
            if decisions.get((a, b)) or decisions.get((b, a)):
                continue
            ca, cb = cards[a], cards[b]
            same_org = bool(ca["org"] and cb["org"]) and (
                normalize.name(ca["org"]) == normalize.name(cb["org"])
            )
            same_bday = bool(ca["birthday"]) and ca["birthday"] == cb["birthday"]
            why = ", ".join(
                w for w, ok in (("same org", same_org), ("same birthday", same_bday)) if ok
            )
            if score >= settings.fuzzy_auto_merge and (same_org or same_bday):
                auto.append((a, b, score))
            else:
                review.append((a, b, score, why or "name only"))
    return auto, review


def _read_decisions(path: Path) -> dict[tuple[str, str], str]:
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        return {
            (r["left"], r["right"]): r["decision"].strip().lower()
            for r in csv.DictReader(f)
            if r.get("decision", "").strip()
        }


def _write_review(
    path: Path,
    review: list[tuple[str, str, float, str]],
    cards: dict[str, dict[str, Any]],
    decisions: dict[tuple[str, str], str],
) -> None:
    """Pending pairs plus PJ's earlier decisions (kept so they survive the rewrite)."""
    if not review and not decisions:
        return
    rows = [
        {
            "left": a,
            "right": b,
            "left_name": cards.get(a, {}).get("name", ""),
            "right_name": cards.get(b, {}).get("name", ""),
            "score": "",
            "why": "",
            "decision": d,
        }
        for (a, b), d in decisions.items()
    ]
    rows += [
        {
            "left": a,
            "right": b,
            "left_name": cards[a]["name"],
            "right_name": cards[b]["name"],
            "score": f"{s:.2f}",
            "why": why,
            "decision": "",
        }
        for a, b, s, why in sorted(review, key=lambda r: -r[2])
    ]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_FIELDS)
        w.writeheader()
        w.writerows(rows)
    path.chmod(0o600)
