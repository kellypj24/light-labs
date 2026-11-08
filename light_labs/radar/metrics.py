"""Per-person metrics as of a date.

A day with a person is *two-way* when it has a message in one direction and the other
direction follows or precedes it within `two_way_window_days`. Day weight, used for
bootstrap circles and "active" 30-day buckets: 3 if two-way else 1, times 1 for a
1:1 conversation, 0.3 for group-only. A bucket is active at weight >= 3: one two-way 1:1
day, three one-way 1:1 days, or about four two-way group days.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import duckdb

ACTIVE_BUCKET_WEIGHT = 3.0


@dataclass(frozen=True)
class PersonMetrics:
    person_id: str
    display_name: str
    org: str | None
    title: str | None
    birthday: date | None
    birthday_has_year: bool | None
    last_contact: datetime | None
    last_channel: str | None
    last_two_way: date | None
    n_90d: int
    n_prev_90d: int
    active_buckets: frozenset[int]  # 30-day buckets back from as_of; 0 = last 30 days

    @property
    def trend(self) -> str:
        if self.n_90d > 1.25 * self.n_prev_90d and self.n_90d - self.n_prev_90d >= 3:
            return "warming"
        if self.n_90d < 0.75 * self.n_prev_90d and self.n_prev_90d - self.n_90d >= 3:
            return "cooling"
        return "steady"

    def active_in(self, first: int, last: int) -> int:
        """Active buckets in [first, last], inclusive."""
        return sum(1 for b in self.active_buckets if first <= b <= last)


def compute(
    con: duckdb.DuckDBPyConnection, as_of: datetime, two_way_window_days: int = 3
) -> list[PersonMetrics]:
    w = int(two_way_window_days)
    rows = con.execute(
        f"""
        WITH pi AS (SELECT * FROM person_interactions WHERE ts <= $as_of),
        daily AS (
            SELECT person_id, (ts AT TIME ZONE 'UTC')::DATE AS d,
                   bool_or(direction = 'sent') AS s,
                   bool_or(direction = 'received') AS r,
                   bool_or(NOT is_group) AS one_on_one
            FROM pi GROUP BY ALL
        ),
        windowed AS (
            SELECT *,
                bool_or(s) OVER win AS s_near,
                bool_or(r) OVER win AS r_near
            FROM daily
            WINDOW win AS (PARTITION BY person_id ORDER BY d
                RANGE BETWEEN INTERVAL {w} DAYS PRECEDING AND INTERVAL {w} DAYS FOLLOWING)
        ),
        days AS (
            SELECT person_id, d,
                (r AND s_near) OR (s AND r_near) AS two_way,
                (CASE WHEN (r AND s_near) OR (s AND r_near) THEN 3 ELSE 1 END)
                    * (CASE WHEN one_on_one THEN 1.0 ELSE 0.3 END) AS weight,
                (($as_of::DATE - d) // 30)::INTEGER AS bucket
            FROM windowed
        ),
        buckets AS (
            SELECT person_id, list(bucket ORDER BY bucket) AS active
            FROM (SELECT person_id, bucket, sum(weight) AS wsum FROM days GROUP BY ALL)
            WHERE wsum >= {ACTIVE_BUCKET_WEIGHT}
            GROUP BY person_id
        ),
        agg AS (
            SELECT person_id,
                max(ts) AS last_contact,
                arg_max(channel, ts) AS last_channel,
                count(*) FILTER (WHERE ts > $as_of - INTERVAL 90 DAYS) AS n_90d,
                count(*) FILTER (WHERE ts > $as_of - INTERVAL 180 DAYS
                                   AND ts <= $as_of - INTERVAL 90 DAYS) AS n_prev_90d
            FROM pi GROUP BY person_id
        ),
        tw AS (SELECT person_id, max(d) AS last_two_way FROM days WHERE two_way GROUP BY ALL)
        SELECT p.person_id, p.display_name, p.org, p.title, p.birthday, p.birthday_has_year,
               a.last_contact, a.last_channel, tw.last_two_way,
               coalesce(a.n_90d, 0), coalesce(a.n_prev_90d, 0), coalesce(b.active, [])
        FROM people p
        LEFT JOIN agg a USING (person_id)
        LEFT JOIN tw USING (person_id)
        LEFT JOIN buckets b USING (person_id)
        WHERE NOT p.is_ignored
        ORDER BY p.display_name
        """,
        {"as_of": as_of},
    ).fetchall()
    return [
        PersonMetrics(
            person_id=r[0],
            display_name=r[1],
            org=r[2],
            title=r[3],
            birthday=r[4],
            birthday_has_year=r[5],
            last_contact=r[6],
            last_channel=r[7],
            last_two_way=r[8],
            n_90d=r[9],
            n_prev_90d=r[10],
            active_buckets=frozenset(r[11]),
        )
        for r in rows
    ]
