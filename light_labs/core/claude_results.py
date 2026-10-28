"""Claude Code's own usage in DuckDB: every transcript record, landed in `raw.claude_records`.

Claude Code writes one JSONL transcript per session under ~/.claude/projects/<dir>/, with
subagents' transcripts beside it, and deletes them after `cleanupPeriodDays` (30 by
default). `raw.claude_records` is the lasting copy: `ingest` appends records it has not
seen, keyed by a hash of the line, and never deletes, so a daily run keeps every session
for good and new dbt models can be built over all of it later.

The records hold full conversations (prompts, replies, tool output). They stay in var/lab.duckdb, which git ignores, and go
nowhere else. Credentials pasted into a session are redacted before a line is stored, and
each ingest re-redacts stored rows and the archive, so a pattern added later cleans the past
too. `record_key` stays the hash of the original line, so a live transcript still holding
the secret is not loaded twice.
"""

import hashlib
import json
import os
import re
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


# (kind, pattern), applied in order: keychain first, since it catches any password after -w.
# Written for both Python re and DuckDB's RE2, which prefilters stored rows.
# Replacements hold no quote or backslash, so a redacted line is still valid JSON.
SECRETS = [
    (
        "keychain",
        r"(add-generic-password[^\"\n]{0,200}?\s-w\s+)(?:'[^'\[][^']*'|[^\s'\"\\\[][^\s'\"\\]*)",
    ),
    ("telegram", r"\b[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}"),
    ("anthropic", r"sk-ant-[A-Za-z0-9_-]{20,}"),
    ("github", r"\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}"),
    ("aws", r"\bAKIA[0-9A-Z]{16}\b"),
    ("google", r"GOCSPX-[A-Za-z0-9_-]{20,}"),
    ("token", r"\b[0-9a-f]{48}\b"),
]
ANY_SECRET = "|".join(f"(?:{p})" for _, p in SECRETS)


def redact(line):
    for kind, pattern in SECRETS:
        # keychain keeps the command (group 1) and drops the password after -w
        repl = rf"\1[REDACTED:{kind}]" if kind == "keychain" else f"[REDACTED:{kind}]"
        line = re.sub(pattern, repl, line)
    return line


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
                yield key, project, transcript, n, redact(line)


def redact_archive(root):
    """Rewrite archived transcripts that still hold a secret; the live ones are Claude Code's."""
    changed = 0
    for path in sorted(Path(root).rglob("*.jsonl")) if Path(root).is_dir() else []:
        text = path.read_text(encoding="utf-8", errors="replace")
        clean = redact(text)
        if clean != text:
            path.write_text(clean, encoding="utf-8")
            changed += 1
    return changed


def _redact_stored(con):
    found = con.execute(
        "SELECT record_key, CAST(record AS VARCHAR) FROM raw.claude_records "
        "WHERE regexp_matches(CAST(record AS VARCHAR), ?)",
        [ANY_SECRET],
    ).fetchall()
    updates = [(redact(text), key) for key, text in found if redact(text) != text]
    if updates:
        con.executemany("UPDATE raw.claude_records SET record = ? WHERE record_key = ?", updates)
    return len(updates)


def ingest(dirs=None, db=None):
    """Append transcript records not loaded before. Returns (new rows, total rows)."""
    if dirs is None:
        redact_archive(config.VAR / "claude" / "projects")
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
        _redact_stored(con)
        con.execute("COMMIT")
        total = con.execute("SELECT count(*) FROM raw.claude_records").fetchone()[0]
    return new, total
