"""DuckDB schema.

Sources write facts: `source_people`, `source_identities` (who a source says exists) and
`interactions` (keyed by identity, not person). `radar.resolve` rebuilds `people` and
`identities` from those facts plus overrides on every sync, so a merge or split never
rewrites interaction history.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_people (
    source VARCHAR NOT NULL,
    source_key VARCHAR NOT NULL,
    display_name VARCHAR,
    org VARCHAR,
    title VARCHAR,
    birthday DATE,
    birthday_has_year BOOLEAN,
    profile_url VARCHAR,
    updated_at TIMESTAMPTZ NOT NULL,
    is_me BOOLEAN NOT NULL DEFAULT false,   -- PJ's own card: its identities are `me`
    PRIMARY KEY (source, source_key)
);
ALTER TABLE source_people ADD COLUMN IF NOT EXISTS is_me BOOLEAN DEFAULT false;

CREATE TABLE IF NOT EXISTS source_identities (
    source VARCHAR NOT NULL,
    source_key VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,          -- phone | email | linkedin_url
    value_norm VARCHAR NOT NULL,
    PRIMARY KEY (source, source_key, kind, value_norm)
);

CREATE TABLE IF NOT EXISTS interactions (
    interaction_id VARCHAR PRIMARY KEY,  -- hash(source, native id, identity)
    identity_kind VARCHAR NOT NULL,
    identity_value VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    channel VARCHAR NOT NULL,
    direction VARCHAR NOT NULL,          -- sent | received
    ts TIMESTAMPTZ NOT NULL,
    is_group BOOLEAN NOT NULL,
    thread_size INTEGER,
    snippet VARCHAR                      -- only with --with-snippets; latest per identity
);

CREATE TABLE IF NOT EXISTS people (
    person_id VARCHAR PRIMARY KEY,
    display_name VARCHAR NOT NULL,
    org VARCHAR,
    title VARCHAR,
    birthday DATE,
    birthday_has_year BOOLEAN,
    is_ignored BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS identities (
    kind VARCHAR NOT NULL,
    value_norm VARCHAR NOT NULL,
    person_id VARCHAR NOT NULL,
    match_method VARCHAR NOT NULL,   -- exact | fuzzy | override | unmatched
    confidence DOUBLE NOT NULL,
    PRIMARY KEY (kind, value_norm)
);

CREATE TABLE IF NOT EXISTS tags (
    person_id VARCHAR NOT NULL,
    tag VARCHAR NOT NULL,
    PRIMARY KEY (person_id, tag)
);

CREATE TABLE IF NOT EXISTS cadence_rules (
    scope VARCHAR NOT NULL,          -- circle | person
    key VARCHAR NOT NULL,            -- circle name or person_id
    circle VARCHAR,
    cadence_days INTEGER,
    PRIMARY KEY (scope, key)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id VARCHAR PRIMARY KEY,
    source VARCHAR NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status VARCHAR NOT NULL,         -- ok | skipped | failed
    watermark VARCHAR,
    rows_in INTEGER,
    message VARCHAR
);

CREATE OR REPLACE VIEW person_interactions AS
SELECT d.person_id, i.*
FROM interactions i
JOIN identities d ON d.kind = i.identity_kind AND d.value_norm = i.identity_value
JOIN people p ON p.person_id = d.person_id
WHERE NOT p.is_ignored;
"""


def connect(path: Path | str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(path))
    con.execute("SET TimeZone = 'UTC'")
    con.execute(SCHEMA)
    return con


def last_watermark(con: duckdb.DuckDBPyConnection, source: str) -> str | None:
    row = con.execute(
        """
        SELECT watermark FROM runs
        WHERE source = ? AND status = 'ok' AND watermark IS NOT NULL
        ORDER BY started_at DESC LIMIT 1
        """,
        [source],
    ).fetchone()
    return row[0] if row else None
