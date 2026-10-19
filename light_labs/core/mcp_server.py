"""The lab as an MCP server (stdio), so an outside agent such as Hermes can read it.

Read-only: the robots' approval queues and Rush's triaged mail. Nothing here sends,
approves or rejects; that stays with PJ (Telegram buttons, the phone page, `lab rush`).
Mail comes out as Rush stored it: sender, subject, label and summary, never a body.

Newline-delimited JSON-RPC 2.0 over stdin/stdout, stdlib only. `lab mcp` runs it.
"""

import json
import sys

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
]

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


HANDLERS = {"queue_pending": queue_pending, "queue_item": queue_item, "mail_recent": mail_recent}


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
        except (TypeError, ValueError, OSError) as e:
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
