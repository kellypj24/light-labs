"""The lab as an MCP server (stdio), so an outside agent such as Hermes can read it.

Reads: the robots' approval queues, Rush's triaged mail, the Agent Net board, GitHub and
each robot's recent journal. One request tool, `rush_present`: Rush puts chosen drafts in
front of PJ in its own Telegram chat with its Send/Reject buttons. Nothing here sends,
posts, approves or rejects; PJ's tap in Rush's chat does that, as before. Mail comes out as Rush stored it:
sender, subject, label and summary, never a body.

Newline-delimited JSON-RPC 2.0 over stdin/stdout, stdlib only. `lab mcp` runs it.
"""

import json
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta

from light_labs import config

PROTOCOL = "2025-06-18"

TOOLS = [
    {
        "name": "queue_pending",
        "description": "Drafts the lab's robots are holding for PJ's approval, oldest first: "
        "id, robot, kind, target, draft text, and whether it was escalated to Auto.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "queue_item",
        "description": "One pending draft by id, with the context the robot drafted from.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "name": "mail_recent",
        "description": "Rush's triage of PJ's recent email, newest first: account, sender, "
        "subject, date, label (needs_reply, unsorted, fyi, receipt, newsletter, spam) and a "
        "one-line summary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "only this label"},
                "account": {"type": "string", "description": "only this mailbox"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "board_tasks",
        "description": "Tasks on the Agent Net board (the lab's shared board with Ketan's "
        "agents) updated in the last `hours`, newest first, excluding done unless asked: id, "
        "title, status, assignee, updated, whether PJ or Rush is mentioned, last comment.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "default": 24},
                "status": {"type": "string", "description": "backlog, doing, review or done"},
                "mentions_only": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "github_status",
        "description": "PJ's GitHub: open PRs he authored (with review decision and checks), "
        "and per watched repo the CI workflows failing on the default branch.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "robot_status",
        "description": "A robot's last journal lines and when its state last changed (rush: "
        "the heartbeat; roll: inbox cleanup, with its last inbox report and when it was "
        "taken; journal lines after that time are newer than the report).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "robot": {"type": "string", "enum": ["rush", "roll"]},
                "lines": {"type": "integer", "default": 10},
            },
            "required": ["robot"],
        },
    },
    {
        "name": "rush_present",
        "description": "Ask Rush to show PJ these pending drafts in Rush's own Telegram chat, "
        "each with Send and Reject buttons. Use when PJ wants to approve or reject drafts: "
        "this does not send anything; PJ's tap on Send in Rush's chat does. At most 10 ids.",
        "inputSchema": {
            "type": "object",
            "properties": {"ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["ids"],
        },
    },
]

# At most this many drafts per rush_present call: one Telegram message each.
PRESENT_MAX = 10

# PJ by name or handle, Rush by name, actor or DLN number.
MENTION = re.compile(r"\b(pj|pj_agent|rush|dln-100)\b", re.IGNORECASE)
EXCERPT = 300

MAIL_FIELDS = ("account", "from", "subject", "date", "label", "summary", "id")


def _pending():
    items = []
    for path in sorted(config.VAR.glob("*/queue/pending/*.json")):
        item = json.loads(path.read_text())
        items.append({"robot": path.parents[2].name, **item})
    return sorted(items, key=lambda i: i.get("created", ""))


def queue_pending():
    return [
        {
            "id": i["id"],
            "robot": i["robot"],
            "kind": i.get("kind"),
            "target": i.get("target"),
            "draft": i.get("draft"),
            "escalated": bool(i.get("escalate")),
            "created": i.get("created"),
        }
        for i in _pending()
    ]


def queue_item(id):
    for item in _pending():
        if item["id"] == id:
            return item
    raise ValueError(f"no pending item {id}")


def mail_recent(label=None, account=None, limit=20):
    rows = []
    for path in sorted((config.VAR / "rush" / "mail").glob("*@*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    rows = [r for r in rows if (not label or r.get("label") == label)]
    rows = [r for r in rows if (not account or r.get("account") == account)]
    rows.reverse()  # each log is appended oldest first
    return [{k: r.get(k) for k in MAIL_FIELDS} for r in rows[: max(1, int(limit))]]


def _when(stamp):
    return datetime.fromisoformat(stamp) if stamp else None


def board_tasks(hours=24, status=None, mentions_only=False, limit=20, client=None):
    from light_labs.core.agentnet import Client

    tasks = (client or Client()).list_tasks()
    tasks = tasks.get("tasks", tasks) if isinstance(tasks, dict) else tasks
    cutoff = datetime.now(UTC) - timedelta(hours=int(hours))
    out = []
    for t in tasks:
        updated = _when(t.get("updatedAt"))
        if updated is None or updated < cutoff:
            continue
        if (status and t.get("status") != status) or (not status and t.get("status") == "done"):
            continue
        comments = t.get("comments") or []
        text = " ".join([t.get("title") or "", t.get("description") or ""]
                        + [c.get("text") or "" for c in comments])  # fmt: skip
        mentioned = bool(MENTION.search(text))
        if mentions_only and not mentioned:
            continue
        last = comments[-1] if comments else None
        out.append({
            "id": t["id"], "title": t.get("title"), "status": t.get("status"),
            "assignee": t.get("assignee"), "updated": t.get("updatedAt"),
            "mentions_pj_or_rush": mentioned, "comments": len(comments),
            "last_comment": last and {"author": last.get("author"), "at": last.get("at"),
                                      "text": (last.get("text") or "")[:EXCERPT]},
        })  # fmt: skip
    out.sort(key=lambda t: t["updated"], reverse=True)
    return out[: max(1, int(limit))]


def _gh(*args, run=subprocess.run):
    done = run(["gh", *args], capture_output=True, text=True, check=True, timeout=60)
    return json.loads(done.stdout or "null")


def github_status(run=subprocess.run):
    prs = _gh("search", "prs", "--author", "@me", "--state", "open", "--json",
              "repository,number,title,url,updatedAt", run=run)  # fmt: skip
    for pr in prs:
        repo = pr.pop("repository", {}).get("nameWithOwner")
        view = _gh("pr", "view", str(pr["number"]), "-R", repo, "--json",
                   "reviewDecision,statusCheckRollup,isDraft", run=run)  # fmt: skip
        checks = [c.get("conclusion") or c.get("status") for c in view["statusCheckRollup"]]
        pr.update(repo=repo, draft=view["isDraft"], review=view["reviewDecision"] or None,
                  checks_failing=sum(c in ("FAILURE", "TIMED_OUT") for c in checks),
                  checks_pending=sum(c in ("IN_PROGRESS", "QUEUED", "PENDING") for c in checks))  # fmt: skip
    watched = config.VAR / "rush" / "github.json"
    failing = {}
    if watched.exists():
        for repo, state in json.loads(watched.read_text()).get("repos", {}).items():
            bad = [name for name, ci in state.get("ci", {}).items() if ci.get("failing")]
            if bad:
                failing[repo] = bad
    return {"open_prs": prs, "ci_failing": failing}


def robot_status(robot, lines=10):
    root = config.VAR / robot
    if robot not in ("rush", "roll") or not root.is_dir():
        raise ValueError(f"no robot {robot}")
    journal = root / "journal.md"
    tail = journal.read_text().splitlines()[-max(1, int(lines)) :] if journal.exists() else []
    out = {"robot": robot, "journal": tail}
    state = root / "state.json"
    if state.exists():
        out["state_updated"] = json.loads(state.read_text()).get("updated_at")
    report = root / "report.json"
    if report.exists():
        r = json.loads(report.read_text())
        taken = datetime.fromtimestamp(report.stat().st_mtime, UTC).isoformat(timespec="seconds")
        out["last_report"] = {"taken": taken, "inbox": r["inbox"], "unread": r["unread"],
                              "rules": {x["id"]: x["count"] for x in r["rules"]}}  # fmt: skip
    return out


def rush_present(ids, telegram=None):
    from light_labs.agents import rush
    from light_labs.agents.rush import phone

    ids = list(dict.fromkeys(ids))
    if not ids or len(ids) > PRESENT_MAX:
        raise ValueError(f"give 1 to {PRESENT_MAX} draft ids")
    pending = {i["id"]: i for i in _pending() if i["robot"] == "rush"}
    missing = [i for i in ids if i not in pending]
    found = [pending[i] for i in ids if i in pending]
    if found:
        if telegram is None:
            if not rush.TELEGRAM_CHAT:
                raise RuntimeError("Rush has no Telegram chat (RUSH_TELEGRAM_CHAT)")
            from light_labs.agents.rush.telegram import Telegram

            telegram = Telegram.from_keychain(
                rush.TELEGRAM_CHAT, config.VAR / "rush" / "telegram.json"
            )
        for item in found:
            telegram.draft(item, phone.text_for(item, rush.REMOTE_URL))
    return {
        "shown_in_rush_chat": [i["id"] for i in found],
        "not_pending": missing,
        "note": "Nothing was sent. PJ taps Send or Reject on each one in Rush's chat.",
    }


HANDLERS = {
    "queue_pending": queue_pending,
    "queue_item": queue_item,
    "mail_recent": mail_recent,
    "board_tasks": board_tasks,
    "github_status": github_status,
    "robot_status": robot_status,
    "rush_present": rush_present,
}


def handle(msg):
    """One JSON-RPC message in; the response, or None for a notification."""
    method, rid = msg.get("method"), msg.get("id")
    if rid is None:
        return None
    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "light-labs", "version": "0.1.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = msg.get("params") or {}
        fn = HANDLERS.get(params.get("name"))
        if fn is None:
            return _error(rid, -32602, f"unknown tool {params.get('name')}")
        try:
            out = fn(**(params.get("arguments") or {}))
            content, is_error = json.dumps(out, indent=1), False
        except (TypeError, ValueError, OSError, RuntimeError, subprocess.SubprocessError) as e:
            content, is_error = str(e), True
        result = {"content": [{"type": "text", "text": content}], "isError": is_error}
    else:
        return _error(rid, -32601, f"method not found: {method}")
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def serve(stdin=sys.stdin, stdout=sys.stdout):
    for line in stdin:
        if not line.strip():
            continue
        try:
            reply = handle(json.loads(line))
        except ValueError:
            reply = _error(None, -32700, "parse error")
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
