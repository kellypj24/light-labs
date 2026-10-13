"""One heartbeat: read what's new, draft responses into the approval queue."""

import re

MAX_CONTEXT_CHARS = 6000
THREAD_COMMENTS = 4
THREAD_CHARS = 1200

_HEADER = re.compile(r"^\s*(\**draft\**:?|subject:.*)\s*$", re.IGNORECASE)
_CLOSING = re.compile(r"^\s*(best|cheers|thanks|regards|warmly)[,!]?\s*$", re.IGNORECASE)
# "Here's the draft:" preambles; whatever follows on the line is the reply.
_PREAMBLE = re.compile(
    r"^.*?\bhere(?:'s| is) (the|my|a) (draft|reply|response)\b[^:\n]*:\s*", re.IGNORECASE
)
# A quoted copy of the incoming message; everything from here on is echo.
_QUOTE = re.compile(r"^\s*(\S+ wrote:|<(message|comment|earlier)\b)", re.IGNORECASE)
# Restated instructions from the system prompt or skills.
_INSTRUCTION = re.compile(
    r"^\s*(never|always|do not|don't) (sign|post|promise|refuse|escalate|mention)\b"
    r"|^\s*you are (writing|posting|replying) as\b"
    r"|^\s*draft \S+'s reply\b",
    re.IGNORECASE,
)


# At a line start in any case, or mid-line in capitals ("...per second. ESCALATE: x").
_ESCALATE = re.compile(r"(?:^\s*\**(?i:escalate)|\s?\**ESCALATE)\**:\s*(.+?)\s*$", re.MULTILINE)


def split_escalation(text):
    """Pull out an `ESCALATE: <work>` line, wherever the model put it."""
    match = _ESCALATE.search(text)
    if not match:
        return None, text
    body = re.sub(r"\n{3,}", "\n\n", text[: match.start()] + text[match.end() :]).strip()
    return match.group(1), body


def strip_echo(text):
    """Drop prompt echo: draft preambles, quoted messages, restated instructions."""
    text = _PREAMBLE.sub("", text, count=1)
    kept = []
    for line in text.splitlines():
        if _QUOTE.match(line):
            break
        if not _INSTRUCTION.match(line):
            kept.append(line)
    return "\n".join(kept)


def clean(text, name="Rush"):
    """Strip the header, sign-off and prompt echo small models add despite instructions."""
    signoff = re.compile(
        rf"^\s*(best|cheers|thanks|regards|warmly)?[,!]?\s*(—\s*)?{name}\.?\s*$", re.IGNORECASE
    )
    lines = strip_echo(text.strip()).strip().splitlines()
    while lines and (not lines[0].strip() or _HEADER.match(lines[0])):
        lines.pop(0)
    while lines and (
        not lines[-1].strip() or signoff.match(lines[-1]) or _CLOSING.match(lines[-1])
    ):
        lines.pop()
    text = "\n".join(lines)
    if len(text) > 1 and text[0] == text[-1] == '"':
        text = text[1:-1].strip()
    return text


# The route call gets its own prompt: a small model asked to classify inside its reply
# persona answers REPLY to nearly everything. Examples are not from the eval fixtures.
ROUTER = """You sort messages that arrive for Rush, a small assistant robot. Rush replies
itself to chat, thanks, greetings, jokes, news, and questions about facts. Anything else
goes to PJ (a person) and Auto (a coding agent). Questions about status, facts, who or
what, or what Rush can do are REPLY even when you don't know the answer: Rush answers them
from his notes. So are compliments. Escalate only these:
- work: code, a script, a review, a fix, a feature, analysis or a comparison,
  benchmarking or measuring, research, a written document, running something
- a decision or commitment PJ has not made: building something, a deadline, joining a
  project, what comes first
- PJ's opinion or assessment of anything

Answer with exactly one line: `ESCALATE: <what needs doing>` or `REPLY`.

Message: "Can you review the parser in v2 and say whether it handles ties?"
ESCALATE: review the v2 parser's tie handling
Message: "Could you measure how long the nightly sync takes and post it?"
ESCALATE: measure the nightly sync's duration
Message: "Will PJ demo the harness at Thursday's sync?"
ESCALATE: decide whether PJ demos at Thursday's sync
Message: "What's PJ's take on the new board layout?"
ESCALATE: PJ's opinion on the new board layout
Message: "Thanks for the update, take your time on the rest."
REPLY
Message: "Which model do you run on these days?"
REPLY
Message: "Where does the release checklist stand?"
REPLY
Message: "Can you read files on the shared drive?"
REPLY
Message: "The new docs read really well, nice job."
REPLY
Message: "Do robots get weekends off?"
REPLY"""
_ROUTED = re.compile(r"^\W*(ESCALATE|REPLY)\b\W*(.*)$", re.IGNORECASE | re.MULTILINE)

HOLDING = (
    "\n\nDecision: this goes to PJ and Auto ({work}). Write only a short holding reply: "
    "say it's with PJ and Auto, and promise no result or date. No ESCALATE line."
)
DIRECT = (
    "\n\nDecision: no escalation. Reply directly from what you know. Don't say you passed "
    "anything to PJ or Auto, and no ESCALATE line."
)


def route(brain, message):
    """One short, deterministic call on the message alone: the escalation, or None."""
    raw = brain.think(ROUTER, f'Message: "{message.strip()}"', temperature=0)
    match = _ROUTED.search(raw)
    if match and match.group(1).upper() == "ESCALATE":
        return match.group(2).strip() or "see the message"
    return None


def draft(brain, system, prompt, message, name, temperature=None):
    """Route, then write: (raw reply, escalation or None, cleaned body).

    Shared by the heartbeat and the evals. The route call decides escalation; the writer
    is told the decision, so a draft can neither miss an escalation nor invent one."""
    escalate = route(brain, message)
    told = prompt + (HOLDING.format(work=escalate) if escalate else DIRECT)
    sampling = {} if temperature is None else {"temperature": temperature}
    raw = brain.think(system, told, **sampling)
    _, body = split_escalation(clean(raw, name))  # drop any ESCALATE line the writer added
    return raw, escalate, body


def reply_prompt(name, sender, summary, content):
    """User prompt for a direct message. Shared by the heartbeat and the evals."""
    return (
        f"A direct message arrived from {sender} "
        f"(subject: {summary or 'none'}).\n"
        f"<message>\n{content}\n</message>\n\nDraft {name}'s reply."
    )


def comment_prompt(name, title, earlier, author, text):
    """User prompt for a new task comment. `earlier` is a list of (author, text)."""
    thread = "\n".join(
        f'<earlier author="{a}">\n{t[:THREAD_CHARS]}\n</earlier>' for a, t in earlier
    )
    return (
        f'Board task "{title}".\nEarlier in the thread:\n'
        f"{thread or '(none)'}\n\nNew comment from {author}:\n"
        f"<comment>\n{text}\n</comment>\n\n"
        f"Draft {name}'s reply comment for the task thread."
    )


def short_id(url):
    return url.rstrip("/").rsplit("/", 1)[-1]


class Heartbeat:
    def __init__(
        self,
        client,
        brain,
        store,
        persona,
        actor,
        watch_tasks,
        name,
        signoff,
        temperature=None,
        meta=None,
    ):
        self.client, self.brain, self.store = client, brain, store
        self.persona, self.actor, self.watch_tasks = persona, actor, watch_tasks
        self.name, self.signoff, self.temperature = name, signoff, temperature
        self.meta = meta or {}  # recorded on every queued draft (brain, commit)

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
            prompt = reply_prompt(self.name, sender, msg.get("summary"), content)
            drafted.append(
                self._draft(
                    "reply",
                    {"to": [sender], "in_reply_to": item["id"], "summary": msg.get("summary")},
                    prompt,
                    f"{sender}: {content[:500]}",
                    content,
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
                earlier = [
                    (p.get("author"), p.get("text") or "")
                    for p in comments[max(0, idx - THREAD_COMMENTS) : idx]
                ]
                prompt = comment_prompt(
                    self.name, task.get("title"), earlier, c.get("author"), text
                )
                drafted.append(
                    self._draft(
                        "comment",
                        {"task_id": task_id},
                        prompt,
                        f"{c.get('author')}: {text[:500]}",
                        text,
                    )
                )
        return drafted

    def _draft(self, kind, target, prompt, context, message):
        system = self.persona(prompt) if callable(self.persona) else self.persona
        _, escalate, body = draft(self.brain, system, prompt, message, self.name, self.temperature)
        item = self.store.enqueue(
            kind,
            target,
            f"{body}\n\n{self.signoff}",
            context,
            escalate=escalate or False,
            **self.meta,
        )
        if escalate:
            (self.store.root / "escalations" / f"{item['id']}.md").write_text(
                f"# Escalation {item['id']}\n\n{escalate}\n\n## Context\n\n{context}\n"
            )
        return item
