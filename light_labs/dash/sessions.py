"""Live Claude Code sessions, the ones waiting on PJ first.

Claude Code keeps one `<pid>.json` per running session in ~/.claude/sessions (session id,
pid, status busy/idle). Only a session whose process is still alive is listed: a recent
log file alone also matches sessions that were closed. The session's log
(~/.claude/projects/*/<sessionId>.jsonl) gives its title, context size and last reply;
only the log's tail is read.
"""

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

CLAUDE = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
TAIL_BYTES = 512 * 1024
REPLY_CLIP = 400
PS_TIME = "%a %b %d %H:%M:%S %Y"  # `ps -o lstart=` in the C locale
START_SLACK = 120  # seconds between a process starting and its session record


def process_starts(pids, run=subprocess.run):
    """{pid: start time as `ps` prints it} for the pids still alive."""
    if not pids:
        return {}
    try:
        out = run(
            ["ps", "-o", "pid=,lstart=", "-p", ",".join(str(p) for p in pids)],
            capture_output=True,
            text=True,
            timeout=5,
            # The registry's procStart is `ps` output in UTC and the C locale.
            env={**os.environ, "TZ": "UTC", "LC_ALL": "C"},
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    starts = {}
    for line in out.splitlines():
        pid, _, started = line.strip().partition(" ")
        if pid.isdigit():
            starts[int(pid)] = " ".join(started.split())
    return starts


def registry(root=None):
    """Every parsable <pid>.json in the registry."""
    out = []
    for path in sorted((root or CLAUDE / "sessions").glob("*.json")):
        try:
            rec = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("sessionId"), str):
            continue
        if type(rec.get("pid")) is int and rec["pid"] > 0 and rec["sessionId"]:
            out.append(rec)
    return out


def _same_process(rec, starts):
    """The pid is alive and is the process that wrote the record, not a reused pid."""
    started = starts.get(rec["pid"])
    if started is None:
        return False
    wrote = " ".join(str(rec.get("procStart") or "").split())
    if wrote:
        return wrote == started
    # No procStart in the record: the session must have begun just after the process.
    try:
        began = datetime.strptime(started, PS_TIME).replace(tzinfo=UTC)
    except ValueError:
        return False
    at = _at(rec.get("startedAt"))
    return at is not None and abs((at - began).total_seconds()) <= START_SLACK


def _tail(path, limit=TAIL_BYTES):
    """The log's last complete records, newest last."""
    try:
        with path.open("rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - limit))
            data = f.read()
    except OSError:
        return []
    lines = data.split(b"\n")
    if size > limit:
        lines = lines[1:]  # the first line is cut mid-record
    out = []
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _context_tokens(usage):
    keys = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    return sum(usage.get(k) or 0 for k in keys)


def log_facts(records):
    """{"title", "context", "reply"} from a log tail; a key is absent when not found."""
    facts = {}
    for rec in reversed(records):
        kind = rec.get("type")
        if kind == "custom-title" and rec.get("customTitle"):
            facts.setdefault("title", rec["customTitle"])
        elif kind == "ai-title" and rec.get("aiTitle"):
            facts.setdefault("title", rec["aiTitle"])
        elif kind == "assistant" and not rec.get("isSidechain"):
            message = rec.get("message") or {}
            if "context" not in facts and isinstance(message.get("usage"), dict):
                facts["context"] = _context_tokens(message["usage"])
            if "reply" not in facts:
                content = message.get("content")
                texts = [
                    b.get("text", "")
                    for b in (content if isinstance(content, list) else [])
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                text = " ".join(" ".join(texts).split())
                if text:
                    facts["reply"] = text[:REPLY_CLIP]
        if len(facts) == 3:
            break
    return facts


def find_log(session_id, projects=None):
    if not all(c.isalnum() or c == "-" for c in session_id):
        return None
    return next(iter((projects or CLAUDE / "projects").glob(f"*/{session_id}.jsonl")), None)


def _at(ms):
    try:
        return datetime.fromtimestamp(ms / 1000, UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def live(root=None, projects=None, starts=process_starts):
    """Live sessions, PJ's turn first (longest-waiting on top), then the busy ones."""
    recs = registry(root)
    alive = starts([r["pid"] for r in recs])
    out = []
    for rec in recs:
        if not _same_process(rec, alive):
            continue
        log = find_log(rec["sessionId"], projects)
        facts = log_facts(_tail(log)) if log else {}
        status = rec.get("status") or "?"
        out.append(
            {
                "pid": rec["pid"],
                "name": rec.get("name") or str(rec["pid"]),
                "title": facts.get("title") or rec.get("name") or "",
                "cwd": Path(rec.get("cwd") or "").name,
                "status": status,
                "waiting": status != "busy",
                "since": _at(rec.get("statusUpdatedAt") or rec.get("updatedAt")),
                "context": facts.get("context"),
                "reply": facts.get("reply", ""),
            }
        )
    epoch = datetime.fromtimestamp(0, UTC)
    out.sort(key=lambda s: (not s["waiting"], s["since"] or epoch))
    return out
