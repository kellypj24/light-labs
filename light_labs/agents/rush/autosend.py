"""Rush's auto-send tier: which drafts go out without PJ's approval.

Drafts the router marked REPLY are eligible; so are escalations' holding replies when
`escalations` is on (the ask itself goes to PJ's daily digest, not the queue). An eligible
draft is sent when every guard passes and no limit is hit; otherwise it waits in the
queue as before. `lab rush flag <id>` marks an auto-sent draft that should not have gone
out and turns auto-send off for its kind until PJ turns it back on.

Settings: `auto_send` on Rush's dln.json entry; RUSH_AUTO_SEND=0 turns it all off.
"""

import json
import os
import re
from datetime import UTC, datetime

# The reply-draft stage's default checks (evals/stages/reply-draft.yaml), which the
# weapon was earned against. tests/test_dbt_model.py keeps the two lists in step.
MUST_NOT_MATCH = [
    r"here'?s (the|my|a) (draft|reply|response)",
    r"^\s*\**draft\**:",
    r"\bas an ai\b",
    r"\bmy (skills|instructions|system prompt)\b",
    r"I (cannot|can't|won't|am unable to) (help|assist|draft|provide|comply)",
    r"unauthori[sz]ed",
    r"^\s*(best|cheers|regards),?\s*$",
    r"—\s*(sam|pj)\b",
]
MAX_CHARS = 900

# Claims of having done something: an auto-sent reply must not report actions nobody took.
# Past tense only: "I run on llama3.1:8b" is a fact about Rush, "I've run it" is a claim.
_DONE = "passed|handed|forwarded|sent|posted|ran|deployed|merged|fixed|scheduled|flagged"
_ACTION = re.compile(
    rf"\bI(?:'ve| have)(?: just)? (?:{_DONE}|run)\b|\bI(?: just)? (?:{_DONE})\b",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://\S+")


def guard(body, incoming):
    """Reasons this draft must not be auto-sent; empty when it may be."""
    reasons = []
    text = body.strip()
    if not text:
        reasons.append("empty draft")
    if len(text) > MAX_CHARS:
        reasons.append(f"longer than {MAX_CHARS} characters")
    for pattern in MUST_NOT_MATCH:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            reasons.append(f"matches /{pattern}/")
    if _ACTION.search(text):
        reasons.append(f"claims an action: {_ACTION.search(text).group(0)!r}")
    for url in _URL.findall(text):
        if url.rstrip(".,)") not in incoming:
            reasons.append(f"link not in the message: {url}")
    return reasons


def thread_key(kind, target):
    return f"task:{target['task_id']}" if kind == "comment" else f"dm:{','.join(target['to'])}"


class Policy:
    """Decides auto-send for one draft from the settings and the queue's history."""

    def __init__(self, settings, store, today=None):
        self.enabled = settings.get("enabled", False) and os.environ.get("RUSH_AUTO_SEND") != "0"
        self.kinds = set(settings.get("kinds", []))
        self.daily_cap = settings.get("daily_cap", 10)
        self.per_thread = settings.get("per_thread", 1)
        # Holding replies to escalations, which promise nothing (heartbeat.HOLDING).
        self.escalations = settings.get("escalations", False)
        self.store = store
        self.today = today or datetime.now(UTC).date().isoformat()

    def _sent(self):
        return sorted(
            (json.loads(p.read_text()) for p in (self.store.root / "queue/sent").glob("*.json")),
            key=lambda i: i.get("resolved", ""),
        )

    def decide(self, kind, target, body, incoming, escalate):
        """(send?, reasons it was held). Reasons are recorded on queued drafts."""
        if not self.enabled:
            return False, ["auto-send off"]
        if escalate and not self.escalations:
            return False, ["escalated"]
        if kind not in self.kinds:
            return False, [f"auto-send not enabled for {kind}"]
        if kind in self.store.load().get("auto_send_off", []):
            return False, [f"auto-send for {kind} turned off after a flag"]
        reasons = guard(body, incoming)
        sent = self._sent()
        auto_today = [i for i in sent if i.get("auto") and i.get("resolved", "")[:10] == self.today]
        if len(auto_today) >= self.daily_cap:
            reasons.append(f"daily cap of {self.daily_cap} reached")
        key = thread_key(kind, target)
        streak = 0
        for item in reversed([i for i in sent if thread_key(i["kind"], i["target"]) == key]):
            if not item.get("auto"):
                break
            streak += 1
        if streak >= self.per_thread:
            reasons.append(f"{streak} auto-replies in a row in this thread; a person goes next")
        return not reasons, reasons
