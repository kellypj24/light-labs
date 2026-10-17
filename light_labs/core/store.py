"""Per-robot on-disk state: what it has seen, its approval queue, and its journal."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, root):
        self.root = Path(root)
        for sub in ("queue/pending", "queue/sent", "queue/rejected", "escalations"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "state.json"

    # --- seen state
    def load(self):
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        return {"seen_messages": [], "seen_comments": {}, "initialized": False}

    def save(self, state):
        state["updated_at"] = now()
        self.state_path.write_text(json.dumps(state, indent=2) + "\n")

    # --- approval queue
    def enqueue(self, kind, target, draft, context, escalate=False, **meta):
        """`draft` may be edited before sending; `drafted` keeps what the robot wrote.
        `meta` records what produced it (brain, commit, dirty) for the queue analytics."""
        item = {
            "id": uuid.uuid4().hex[:8],
            "kind": kind,
            "target": target,
            "draft": draft,
            "drafted": draft,
            "context": context,
            "escalate": escalate,
            "created": now(),
            **meta,
        }
        self._path("pending", item["id"]).write_text(json.dumps(item, indent=2) + "\n")
        return item

    def pending(self):
        return sorted(
            (json.loads(p.read_text()) for p in (self.root / "queue/pending").glob("*.json")),
            key=lambda i: i["created"],
        )

    def get(self, item_id):
        return json.loads(self._path("pending", item_id).read_text())

    def update(self, item_id, **fields):
        """Change a pending item in place (PJ's edit to a draft)."""
        item = self.get(item_id)
        item.update(fields)
        self._path("pending", item_id).write_text(json.dumps(item, indent=2) + "\n")
        return item

    def resolve(self, item_id, outcome, **extra):
        item = self.get(item_id)
        item.update(extra, resolved=now())
        self._path(outcome, item_id).write_text(json.dumps(item, indent=2) + "\n")
        self._path("pending", item_id).unlink()
        return item

    def _path(self, bucket, item_id):
        return self.root / "queue" / bucket / f"{item_id}.json"

    # --- journal
    def journal(self, line):
        with (self.root / "journal.md").open("a") as f:
            f.write(f"- {now()} {line}\n")
