"""Robots' approval queues in DuckDB: every queued draft, landed in `raw.queue_items`.

The queue files under var/<robot>/queue/{pending,sent,rejected}/ stay the source of truth.
`ingest` reloads them in full (they are small), beside the eval results in var/lab.duckdb;
the dbt project models approval rates and autonomy readiness on top.
"""

import json
from pathlib import Path

from light_labs import config
from light_labs.evals import results

STATUSES = ("pending", "sent", "rejected")

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE TABLE IF NOT EXISTS raw.queue_items (
    item_id VARCHAR NOT NULL,
    robot VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    kind VARCHAR,
    target JSON,
    draft VARCHAR,
    drafted VARCHAR,
    context VARCHAR,
    escalation VARCHAR,
    created TIMESTAMPTZ,
    resolved TIMESTAMPTZ,
    result_id VARCHAR,
    reason VARCHAR,
    brain VARCHAR,
    "commit" VARCHAR,
    dirty BOOLEAN,
    source VARCHAR NOT NULL
);
"""

COLUMNS = [
    "item_id",
    "robot",
    "status",
    "kind",
    "target",
    "draft",
    "drafted",
    "context",
    "escalation",
    "created",
    "resolved",
    "result_id",
    "reason",
    "brain",
    "commit",
    "dirty",
    "source",
]


def _row(robot, status, path):
    item = json.loads(path.read_text())
    escalate = item.get("escalate")
    return (
        item["id"],
        robot,
        status,
        item.get("kind"),
        json.dumps(item.get("target")),
        item.get("draft"),
        item.get("drafted"),  # absent on items queued before it was recorded
        item.get("context"),
        escalate if isinstance(escalate, str) and escalate else None,
        item.get("created"),
        item.get("resolved"),
        item.get("result_id"),
        item.get("reason"),
        item.get("brain"),
        item.get("commit"),
        item.get("dirty"),
        str(path),
    )


def ingest(root=None, db=None):
    """Reload raw.queue_items from <root>/<robot>/queue/*/. Returns {robot: items}."""
    root = Path(root or config.VAR)
    rows = []
    for queue in sorted(root.glob("*/queue")):
        for status in STATUSES:
            for path in sorted((queue / status).glob("*.json")):
                rows.append(_row(queue.parent.name, status, path))
    with results.connect(db) as con:
        con.execute(SCHEMA)
        con.execute("BEGIN")
        con.execute("DELETE FROM raw.queue_items")
        if rows:
            cols = ", ".join(f'"{c}"' for c in COLUMNS)
            marks = ", ".join("?" for _ in COLUMNS)
            con.executemany(f"INSERT INTO raw.queue_items ({cols}) VALUES ({marks})", rows)
        con.execute("COMMIT")
    loaded = {}
    for row in rows:
        loaded[row[1]] = loaded.get(row[1], 0) + 1
    return loaded
