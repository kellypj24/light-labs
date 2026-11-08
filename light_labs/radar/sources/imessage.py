"""iMessage/SMS from the helper's export (`helper/radar-messages-export.swift`).

This module never opens chat.db: only the helper holds Full Disk Access. The export is
newline-delimited JSON with two record types:

    {"type": "chat", "chat": "<guid>", "members": ["+15551234567", "a@b.com"]}
    {"type": "message", "rowid": 1, "guid": "...", "from_me": true, "date": 7.2e17,
     "sender": null, "chat": "<guid>", "service": "iMessage", "text": "..."}

`text` is present only in a helper built with snippets. Received messages count for the
sender; sent messages count for every member of the chat. Watermark: the highest rowid.
"""

from __future__ import annotations

import duckdb

from light_labs.radar import normalize
from light_labs.radar.sources.base import SourceResult, SourceSkipped, SyncContext

COLUMNS = {
    "type": "VARCHAR",
    "chat": "VARCHAR",
    "members": "VARCHAR[]",
    "rowid": "BIGINT",
    "guid": "VARCHAR",
    "from_me": "BOOLEAN",
    "date": "BIGINT",
    "sender": "VARCHAR",
    "service": "VARCHAR",
    "text": "VARCHAR",
}


class IMessageSource:
    name = "imessage"

    def sync(
        self, con: duckdb.DuckDBPyConnection, ctx: SyncContext, watermark: str | None
    ) -> SourceResult:
        path = ctx.paths.messages_export
        if not path.exists():
            raise SourceSkipped(f"no export at {path}; run `lab radar doctor`")
        since = int(watermark) if watermark else -1

        con.execute(
            "CREATE OR REPLACE TEMP TABLE msg_raw AS SELECT * FROM read_json(?, "
            "format = 'newline_delimited', columns = " + _struct(COLUMNS) + ")",
            [str(path)],
        )
        handles = con.execute(
            """
            SELECT DISTINCT h FROM (
                SELECT sender AS h FROM msg_raw WHERE type = 'message' AND rowid > ?
                UNION ALL
                SELECT unnest(members) FROM msg_raw WHERE type = 'chat'
            ) WHERE h IS NOT NULL
            """,
            [since],
        ).fetchall()
        mapping = []
        for (raw,) in handles:
            parsed = normalize.handle(raw, ctx.settings.default_region)
            if parsed:
                mapping.append((raw, *parsed))
        con.execute(
            "CREATE OR REPLACE TEMP TABLE handle_map (raw VARCHAR, kind VARCHAR, value VARCHAR)"
        )
        if mapping:
            con.executemany("INSERT INTO handle_map VALUES (?, ?, ?)", mapping)

        snippet = "left(text, 140)" if ctx.with_snippets else "NULL"
        before = con.execute("SELECT count(*) FROM interactions").fetchone()[0]
        con.execute(
            f"""
            INSERT OR IGNORE INTO interactions
            WITH chats AS (
                SELECT chat, unnest(members) AS raw, len(members) AS n
                FROM msg_raw WHERE type = 'chat'
            ),
            members AS (
                SELECT c.chat, c.n, h.kind, h.value
                FROM chats c JOIN handle_map h USING (raw)
            ),
            sizes AS (SELECT DISTINCT chat, n FROM chats),
            msgs AS (
                SELECT * FROM msg_raw WHERE type = 'message' AND rowid > ? AND date IS NOT NULL
            ),
            counterparts AS (
                SELECT m.*, h.kind, h.value, coalesce(s.n, 1) AS n, 'received' AS direction
                FROM msgs m
                JOIN handle_map h ON h.raw = m.sender
                LEFT JOIN sizes s ON s.chat = m.chat
                WHERE NOT m.from_me
                UNION ALL
                SELECT m.*, mb.kind, mb.value, mb.n, 'sent' AS direction
                FROM msgs m JOIN members mb ON mb.chat = m.chat
                WHERE m.from_me
            )
            SELECT
                left(sha256('imessage|' || guid || '|' || kind || ':' || value), 16),
                kind,
                value,
                'imessage',
                CASE service WHEN 'SMS' THEN 'sms' WHEN 'RCS' THEN 'rcs' ELSE 'imessage' END,
                direction,
                {_apple_ts_sql("date")},
                n > 1,
                n + 1,
                {snippet}
            FROM counterparts
            """,
            [since],
        )
        added = con.execute("SELECT count(*) FROM interactions").fetchone()[0] - before
        _keep_latest_snippet(con)
        top = con.execute("SELECT max(rowid) FROM msg_raw WHERE type = 'message'").fetchone()[0]
        new_mark = str(max(top, since)) if top is not None else watermark
        return SourceResult(watermark=new_mark, rows_in=added)


def _struct(cols: dict[str, str]) -> str:
    return "{" + ", ".join(f"'{k}': '{v}'" for k, v in cols.items()) + "}"


def _apple_ts_sql(col: str) -> str:
    """Nanoseconds since 2001-01-01 (seconds on pre-10.13 rows), as TIMESTAMPTZ."""
    epoch = "TIMESTAMPTZ '2001-01-01 00:00:00+00'"
    return (
        f"CASE WHEN abs({col}) > 100000000000 "
        f"THEN {epoch} + to_microseconds({col} // 1000) "
        f"ELSE {epoch} + to_seconds({col}) END"
    )


def _keep_latest_snippet(con: duckdb.DuckDBPyConnection) -> None:
    """One preview per contact: clear every snippet but the newest per identity."""
    con.execute(
        """
        UPDATE interactions SET snippet = NULL
        WHERE snippet IS NOT NULL AND interaction_id NOT IN (
            SELECT arg_max(interaction_id, ts) FROM interactions
            WHERE snippet IS NOT NULL
            GROUP BY identity_kind, identity_value
        )
        """
    )
