"""One heartbeat: read what's new, draft responses into the approval queue."""

import re

MAX_CONTEXT_CHARS = 6000
THREAD_COMMENTS = 4
THREAD_CHARS = 1200

_HEADER = re.compile(r"^\s*(\**draft\**:?|subject:.*)\s*$", re.IGNORECASE)
_CLOSING = re.compile(r"^\s*(best|cheers|thanks|regards|warmly)[,!]?\s*$", re.IGNORECASE)


def split_escalation(text):
    first, _, rest = text.partition("\n")
    if first.upper().startswith("ESCALATE:"):
        return first.split(":", 1)[1].strip(), rest.strip()
    return None, text


def clean(text, name="Rush"):
    """Strip the header and sign-off lines small models add despite instructions."""
    signoff = re.compile(
        rf"^\s*(best|cheers|thanks|regards|warmly)?[,!]?\s*(—\s*)?{name}\.?\s*$", re.IGNORECASE
    )
    lines = text.strip().splitlines()
    while lines and (not lines[0].strip() or _HEADER.match(lines[0])):
        lines.pop(0)
    while lines and (
        not lines[-1].strip() or signoff.match(lines[-1]) or _CLOSING.match(lines[-1])
    ):
        lines.pop()
    return "\n".join(lines)


def short_id(url):
    return url.rstrip("/").rsplit("/", 1)[-1]


class Heartbeat:
    def __init__(self, client, brain, store, persona, actor, watch_tasks, name, signoff):
        self.client, self.brain, self.store = client, brain, store
        self.persona, self.actor, self.watch_tasks = persona, actor, watch_tasks
        self.name, self.signoff = name, signoff

    def tick(self, backfill=False):
        state = self.store.load()
        # First run: mark the existing backlog as seen unless asked to backfill.
        seed = not state["initialized"] and not backfill
        drafted = self._inbox(state, seed) + self._tasks(state, seed)
        state["initialized"] = True
        self.store.save(state)
        self.store.journal(f"tick: {len(drafted)} draft(s)" + (" (seeded backlog)" if seed else ""))
        return drafted

    def _inbox(self, state, seed):
        drafted = []
        for item in self.client.inbox(self.actor).get("items", []):
            mid = short_id(item["id"])
            sender = short_id(item["attributedTo"])
            if mid in state["seen_messages"]:
                continue
            state["seen_messages"].append(mid)
            if seed or sender == self.actor or item.get("broadcast"):
                continue
            msg = self.client.message(mid)
            content = (msg.get("content") or "")[:MAX_CONTEXT_CHARS]
            prompt = (
                f"A direct message arrived from {sender} "
                f"(subject: {msg.get('summary') or 'none'}).\n"
                f"<message>\n{content}\n</message>\n\nDraft {self.name}'s reply."
            )
            drafted.append(
                self._draft(
                    "reply",
                    {"to": [sender], "in_reply_to": item["id"], "summary": msg.get("summary")},
                    prompt,
                    f"{sender}: {content[:500]}",
                )
            )
        return drafted

    def _tasks(self, state, seed):
        drafted = []
        for task_id in self.watch_tasks:
            task = self.client.task(task_id)
            comments = task.get("comments", [])
            seen = state["seen_comments"].get(task_id, 0)
            state["seen_comments"][task_id] = len(comments)
            if seed:
                continue
            for idx in range(seen, len(comments)):
                c = comments[idx]
                if c.get("author") == self.actor:
                    continue
                text = (c.get("text") or "")[:MAX_CONTEXT_CHARS]
                earlier = "\n".join(
                    f'<earlier author="{p.get("author")}">\n'
                    f"{(p.get('text') or '')[:THREAD_CHARS]}\n</earlier>"
                    for p in comments[max(0, idx - THREAD_COMMENTS) : idx]
                )
                prompt = (
                    f'Board task "{task.get("title")}".\nEarlier in the thread:\n'
                    f"{earlier or '(none)'}\n\nNew comment from {c.get('author')}:\n"
                    f"<comment>\n{text}\n</comment>\n\n"
                    f"Draft {self.name}'s reply comment for the task thread."
                )
                drafted.append(
                    self._draft(
                        "comment", {"task_id": task_id}, prompt, f"{c.get('author')}: {text[:500]}"
                    )
                )
        return drafted

    def _draft(self, kind, target, prompt, context):
        raw = self.brain.think(self.persona, prompt)
        escalate, body = split_escalation(clean(raw, self.name))
        item = self.store.enqueue(
            kind, target, f"{body}\n\n{self.signoff}", context, escalate=escalate or False
        )
        if escalate:
            (self.store.root / "escalations" / f"{item['id']}.md").write_text(
                f"# Escalation {item['id']}\n\n{escalate}\n\n## Context\n\n{context}\n"
            )
        return item
