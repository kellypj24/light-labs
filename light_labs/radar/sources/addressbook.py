"""Contacts from the Mac's Contacts databases, through the helper's contacts.jsonl.

The helper (the only code with Full Disk Access) reads the root AddressBook database and
one per account under Sources/. Records:

    {"type": "contact", "uid": "...", "first": "Ana", "last": "Example", "nickname": null,
     "org": "...", "title": "...", "birthday": 3.1e8, "me": false,
     "phones": ["(415) 555-0101"], "emails": ["ana@example.com"]}
    {"type": "error", "source": "contacts", "message": "..."}

`birthday` is seconds since 2001-01-01; year 1604 means Contacts has no year. The card
marked `me` is PJ's own: its phones and emails are never a person. Each sync replaces
this source's people, so a deleted card disappears. The file is deleted once read.
"""

from __future__ import annotations

import json
from datetime import timedelta

import duckdb

from light_labs.radar import normalize
from light_labs.radar.sources.base import (
    SourceResult,
    SourceSkipped,
    SyncContext,
    put_person,
)


class AddressBookSource:
    name = "addressbook"

    def sync(
        self, con: duckdb.DuckDBPyConnection, ctx: SyncContext, watermark: str | None
    ) -> SourceResult:
        path = ctx.paths.contacts_export
        if not path.exists():
            raise SourceSkipped(f"no export at {path}; run `lab radar doctor`")
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        cards = [r for r in records if r.get("type") == "contact"]
        errors = [r["message"] for r in records if r.get("type") == "error"]
        if not cards:
            # Keep what an earlier sync stored rather than wiping it on a bad read.
            path.unlink()
            raise SourceSkipped("; ".join(errors) or "no contacts in the export")

        region = ctx.settings.default_region
        con.execute("DELETE FROM source_identities WHERE source = 'addressbook'")
        con.execute("DELETE FROM source_people WHERE source = 'addressbook'")
        seen: set[str] = set()
        for c in cards:
            uid = c["uid"]
            if uid in seen:  # the same card through two accounts
                continue
            seen.add(uid)
            name = " ".join(x for x in (c.get("first"), c.get("last")) if x) or c.get("org")
            if not name:
                continue
            idents = {
                ("phone", p) for raw in c.get("phones", []) if (p := normalize.phone(raw, region))
            }
            idents |= {("email", e) for raw in c.get("emails", []) if (e := normalize.email(raw))}
            bday, has_year = None, None
            if c.get("birthday") is not None:
                d = (normalize.APPLE_EPOCH + timedelta(seconds=c["birthday"])).date()
                bday, has_year = d, d.year != 1604
            put_person(
                con, "addressbook", uid, name, idents, org=c.get("org"),
                title=c.get("title"), birthday=bday, birthday_has_year=has_year,
                is_me=bool(c.get("me")),
            )  # fmt: skip
        path.unlink()
        return SourceResult(rows_in=len(seen), message="; ".join(errors) or None)
