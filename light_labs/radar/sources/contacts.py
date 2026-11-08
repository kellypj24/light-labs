"""Contacts from vCard exports (Contacts.app: select all, File > Export > Export vCard).

No macOS permission is needed: PJ drops `.vcf` files into `~/.relationship-radar/inbox/
contacts/`. Each sync replaces this source's people with what the files say now, so a
deleted card disappears. Watermark: a hash of the files' names, sizes and mtimes;
unchanged files skip the sync.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import duckdb

from light_labs.radar import normalize
from light_labs.radar.sources.base import SourceResult, SourceSkipped, SyncContext


@dataclass
class Card:
    uid: str | None = None
    full_name: str | None = None
    structured_name: str | None = None
    org: str | None = None
    title: str | None = None
    birthday: date | None = None
    birthday_has_year: bool = True
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)

    @property
    def name(self) -> str | None:
        return self.full_name or self.structured_name or self.org


class ContactsSource:
    name = "contacts"

    def sync(
        self, con: duckdb.DuckDBPyConnection, ctx: SyncContext, watermark: str | None
    ) -> SourceResult:
        files = sorted(ctx.paths.contacts_dir.glob("*.vcf"))
        if not files:
            raise SourceSkipped(f"no .vcf files in {ctx.paths.contacts_dir}")
        # Name, size and mtime of every file: a removed or replaced export changes it too.
        newest = normalize.stable_id(
            *(f"{f.name}:{f.stat().st_size}:{f.stat().st_mtime_ns}" for f in files)
        )
        if watermark == newest:
            return SourceResult(status="ok", watermark=newest, message="unchanged")

        con.execute("DELETE FROM source_identities WHERE source = 'contacts'")
        con.execute("DELETE FROM source_people WHERE source = 'contacts'")
        now = datetime.now(UTC)
        n = 0
        for card in (c for f in files for c in parse_vcards(f.read_text(errors="replace"))):
            if not card.name:
                continue
            idents = {
                ("phone", p)
                for raw in card.phones
                if (p := normalize.phone(raw, ctx.settings.default_region))
            }
            idents |= {("email", e) for raw in card.emails if (e := normalize.email(raw))}
            key = card.uid or normalize.stable_id(card.name, *sorted(v for _, v in idents))
            con.execute(
                "INSERT OR REPLACE INTO source_people VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                [
                    "contacts",
                    key,
                    card.name,
                    card.org,
                    card.title,
                    card.birthday,
                    card.birthday_has_year if card.birthday else None,
                    now,
                ],
            )
            for kind, value in idents:
                con.execute(
                    "INSERT OR IGNORE INTO source_identities VALUES ('contacts', ?, ?, ?)",
                    [key, kind, value],
                )
            n += 1
        return SourceResult(watermark=newest, rows_in=n)


def parse_vcards(text: str) -> list[Card]:
    """vCard 3.0 as Contacts.app writes it: folded lines, `item1.` groups, escaped values."""
    lines = re.sub(r"\r?\n[ \t]", "", text).splitlines()
    cards: list[Card] = []
    card: Card | None = None
    for line in lines:
        if ":" not in line:
            continue
        head, value = line.split(":", 1)
        prop, *params = head.split(";")
        prop = prop.split(".")[-1].upper()
        params_upper = [p.upper() for p in params]
        if prop == "BEGIN":
            card = Card()
        elif prop == "END" and card is not None:
            cards.append(card)
            card = None
        elif card is None:
            continue
        elif prop == "UID" or prop == "X-ABUID":
            card.uid = card.uid or value.strip()
        elif prop == "FN":
            card.full_name = _unescape(value).strip() or None
        elif prop == "N":
            parts = [_unescape(p).strip() for p in value.split(";")]
            given = " ".join(p for p in (parts[1:2] + parts[0:1]) if p)
            card.structured_name = given or None
        elif prop == "ORG":
            card.org = _unescape(value.split(";")[0]).strip() or None
        elif prop == "TITLE":
            card.title = _unescape(value).strip() or None
        elif prop == "BDAY":
            card.birthday, card.birthday_has_year = _birthday(value, params_upper)
        elif prop == "TEL":
            card.phones.append(value.strip())
        elif prop == "EMAIL":
            card.emails.append(value.strip())
    return cards


def _unescape(v: str) -> str:
    return v.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _birthday(value: str, params: list[str]) -> tuple[date | None, bool]:
    """`1985-03-15`, `19850315`, `--0315`, or Apple's `1604-03-15` with X-APPLE-OMIT-YEAR."""
    v = value.strip().split("T")[0]
    omit_year = any(p.startswith("X-APPLE-OMIT-YEAR") for p in params)
    m = re.fullmatch(r"--(\d{2})-?(\d{2})", v)
    if m:
        return date(1604, int(m[1]), int(m[2])), False
    m = re.fullmatch(r"(\d{4})-?(\d{2})-?(\d{2})", v)
    if not m:
        return None, False
    try:
        d = date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None, False
    return d, not (omit_year or d.year == 1604)
