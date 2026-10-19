"""Claude Code's own usage in DuckDB: every transcript record, landed in `raw.claude_records`.

Claude Code writes one JSONL transcript per session under ~/.claude/projects/<dir>/, with
subagents' transcripts beside it, and deletes them after `cleanupPeriodDays` (30 by
default). `raw.claude_records` is the lasting copy: `ingest` appends records it has not
seen, keyed by a hash of the line, and never deletes, so a daily run keeps every session
for good and new dbt models can be built over all of it later.

The records hold full conversations (prompts, replies, tool output). They stay in var/lab.duckdb, which git ignores, and go
nowhere else.
"""

import hashlib
import json
import os
from pathlib import Path

from light_labs import config
from light_labs.evals import results

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE TABLE IF NOT EXISTS raw.claude_records (
    record_key VARCHAR PRIMARY KEY,
    project_dir VARCHAR NOT NULL,
    transcript VARCHAR NOT NULL,
    line_no INTEGER NOT NULL,
    record JSON NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def claude_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))


def project_dirs():
    """Where transcripts live, plus an archive copied there before they expire."""
    live = os.environ.get("LAB_CLAUDE_PROJECTS", claude_dir() / "projects")
    return [Path(live), config.VAR / "claude" / "projects"]


def _lines(path):
    """(line_no, line, parsed) for each whole JSON line; a line cut off mid-write is
    skipped and the next run gets it whole."""
    with path.open(encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield n, line, json.loads(line)
            except ValueError:
                continue


def _records(dirs):
    """(key, project_dir, transcript, line_no, line) for every transcript line."""
    for root in dirs:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.jsonl")):
            project = path.relative_to(root).parts[0]
            transcript = str(path.relative_to(root / project))
            for n, line, _ in _lines(path):
                key = hashlib.sha256(line.encode()).hexdigest()
                yield key, project, transcript, n, line


def ingest(dirs=None, db=None):
    """Append transcript records not loaded before. Returns (new rows, total rows)."""
    rows, seen = [], set()
    for row in _records(project_dirs() if dirs is None else [Path(d) for d in dirs]):
        if row[0] not in seen:  # the same file in ~/.claude and the archive
            seen.add(row[0])
            rows.append(row)
    with results.connect(db) as con:
        con.execute(SCHEMA)
        con.execute("BEGIN")
        con.execute("CREATE TEMP TABLE incoming AS SELECT * FROM raw.claude_records LIMIT 0")
        if rows:
            con.executemany(
                "INSERT INTO incoming (record_key, project_dir, transcript, line_no, record) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
        new = con.execute(
            "INSERT INTO raw.claude_records (record_key, project_dir, transcript, line_no, record) "
            "SELECT record_key, project_dir, transcript, line_no, record FROM incoming i "
            "WHERE NOT EXISTS (SELECT 1 FROM raw.claude_records r "
            "WHERE r.record_key = i.record_key)"
        ).fetchone()[0]
        con.execute("COMMIT")
        total = con.execute("SELECT count(*) FROM raw.claude_records").fetchone()[0]
    return new, total
