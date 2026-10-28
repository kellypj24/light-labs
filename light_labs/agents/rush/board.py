"""`lab board`: Auto's access to Agent Net, through Rush (#72).

Reads come from Rush's cache (board.json, written every tick); `--live` fetches now and
rewrites it. Posts go out as Rush's actor, signed as Auto's, through Rush's auto-send
policy with author="auto" (autosend.py); a held post waits in Rush's queue for PJ. The
token stays in the keychain: agentnet.Client reads it, nothing takes it as an argument.
"""

import json
import re
from datetime import UTC, datetime

from light_labs.agents.rush.autosend import thread_key
from light_labs.agents.rush.heartbeat import post as send_item
from light_labs.agents.rush.heartbeat import short_id
from light_labs.agents.rush.remote import board_view
from light_labs.core.store import now

CACHE = "board.json"
STALE_HOURS = 2
LIMIT = 20
CLIP = 100


def load(root):
    path = root / CACHE
    return json.loads(path.read_text()) if path.exists() else None


def save(root, inbox, tasks=None, messages=None):
    """Write the cache. Message bodies from earlier saves are kept while their message is
    still in the inbox; `tasks=None` keeps the cached tasks."""
    old = load(root) or {}
    ids = {short_id(i["id"]) for i in inbox}
    kept = {k: v for k, v in old.get("messages", {}).items() if k in ids}
    kept.update(messages or {})
    snap = {
        "at": now(),
        "inbox": inbox,
        "tasks": old.get("tasks", []) if tasks is None else tasks,
        "messages": kept,
    }
    (root / CACHE).write_text(json.dumps(snap) + "\n")
    return snap


def fetch(client, actor, root):
    """Refresh the cache from the edge: inbox, every task, and inbox bodies not yet cached.
    Rush's seen state is not touched, so his next tick still drafts for what is new."""
    inbox = client.inbox(actor).get("items", [])
    cached = (load(root) or {}).get("messages", {})
    bodies = {
        short_id(i["id"]): client.message(short_id(i["id"]))
        for i in inbox
        if short_id(i["id"]) not in cached
    }
    return save(root, inbox, client.list_tasks(), bodies)


def one_line(text, clip=CLIP):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= clip else text[: clip - 1] + "…"


def age(snap, at=None):
    """The cache's age as text, and whether it is stale."""
    at = at or datetime.now(UTC)
    hours = (at - datetime.fromisoformat(snap["at"])).total_seconds() / 3600
    text = f"{hours * 60:.0f}m" if hours < 1 else f"{hours:.1f}h"
    return text, hours > STALE_HOURS


def overview(snap, actor, limit=LIMIT, at=None):
    """Inbox, then tasks naming PJ, Rush or the actor, newest first: one line each."""
    text, stale = age(snap, at)
    lines = [f"cache {snap['at']} ({text} old{'; stale, use --live' if stale else ''})"]
    inbox = [i for i in snap["inbox"] if short_id(i["attributedTo"]) != actor]
    inbox.sort(key=lambda i: i.get("published") or "", reverse=True)
    lines.append(f"inbox ({len(inbox)}):")
    for i in inbox[:limit]:
        mid = short_id(i["id"])
        body = snap["messages"].get(mid, {}).get("content")
        lines.append(
            f"  {mid}  {(i.get('published') or '')[:16]}  {short_id(i['attributedTo'])}"
            f"{'  [all]' if i.get('broadcast') else ''}  "
            + one_line(i.get("summary") or body or "")
        )
    tasks = board_view(snap["tasks"], actor, limit)
    lines.append(f"tasks naming PJ or Rush ({len(tasks)}):")
    for t in tasks:
        lines.append(
            f"  {t['id']}  {(t.get('updatedAt') or '')[:16]}  {t.get('status') or ''}  "
            + one_line(t.get("title"), 70)
        )
        if t.get("comments"):
            c = t["comments"][-1]
            lines.append(f"    {c.get('author')}: {one_line(c.get('text'))}")
    return "\n".join(lines)


def find(snap, ref):
    """("task" | "message", record) for an id in the cache, or None. A message whose
    body is not cached comes back as its inbox item."""
    if ref in snap["messages"]:
        return "message", snap["messages"][ref]
    for i in snap["inbox"]:
        if short_id(i["id"]) == ref:
            return "message", i
    for t in snap["tasks"]:
        if t["id"] == ref:
            return "task", t
    return None


def show(kind, record):
    """One message or task in full."""
    if kind == "message":
        head = [
            f"from: {short_id(record.get('attributedTo') or '')}",
            f"to: {', '.join(short_id(t) for t in record.get('to') or []) or '?'}",
            f"published: {record.get('published')}",
            f"summary: {record.get('summary') or ''}",
        ]
        if record.get("inReplyTo"):
            head.append(f"in reply to: {short_id(record['inReplyTo'])}")
        body = record.get("content")
        return "\n".join(head) + "\n\n" + (body if body is not None else "(body not cached)")
    lines = [
        f"{record['id']}  {record.get('status')}  {record.get('title')}",
        f"by {record.get('createdBy')} {record.get('createdAt')}; assignee "
        + f"{record.get('assignee')}; updated {record.get('updatedAt')}",
        "",
        record.get("description") or "(no description)",
    ]
    for c in record.get("comments") or []:
        lines += ["", f"[{c.get('at')}] {c.get('author')}:", c.get("text") or ""]
    return "\n".join(lines)


def post(client, store, policy, actor, signoff, kind, target, text, dry_run=False):
    """Send Auto's post if Rush's policy allows it, else queue it for PJ. Returns
    (item or None on a dry run, reasons held). A post replaces Rush's pending drafts for
    the same thread, as a newer Rush draft would."""
    text = text.strip()
    send, held = policy.decide(kind, target, text, "", False, author="auto")
    if dry_run:
        return None, held
    where = target.get("task_id") or ", ".join(target["to"])
    item = store.enqueue(
        kind,
        target,
        f"{text}\n\n{signoff}",
        f"Auto to {where}",
        author="auto",
        brain="claude",
        **({} if send else {"held": held}),
    )
    key = thread_key(kind, target)
    for old in store.pending():
        if old["id"] != item["id"] and thread_key(old["kind"], old["target"]) == key:
            store.resolve(old["id"], "rejected", reason=f"superseded by {item['id']}")
            store.journal(f"{old['id']} superseded by Auto's {item['id']}")
    if not send:
        store.journal(f"Auto's post {item['id']} held: {'; '.join(held)}")
        return item, held
    result = send_item(client, actor, item)  # OSError: stays pending for PJ
    item = store.resolve(item["id"], "sent", result_id=result.get("id"), auto=True)
    store.journal(f"Auto posted {item['id']} ({kind} to {where})")
    return item, []
