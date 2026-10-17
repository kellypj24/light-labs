"""Minimal Agent Net edge client. Stdlib only."""

import json
import subprocess
import time
import urllib.error
import urllib.request

from light_labs import config


def keychain_token(service=config.KEYCHAIN_SERVICE):
    return subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


# The edge rate-limits bursts with 429.
RETRIES = 3
BACKOFF = 5


class Client:
    def __init__(self, base=config.EDGE, token=None, timeout=30):
        if not base:
            raise RuntimeError("LAB_EDGE is not set; add it to .env (see .env.example)")
        self.base = base.rstrip("/")
        self._token = token
        self.timeout = timeout

    @property
    def token(self):
        if self._token is None:
            self._token = keychain_token()
        return self._token

    def _call(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        for attempt in range(RETRIES + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode()
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 or attempt == RETRIES:
                    raise
                time.sleep(BACKOFF * (attempt + 1))
        # The edge emits unescaped control characters in some strings.
        return json.loads(raw, strict=False) if raw else {}

    def inbox(self, actor):
        return self._call("GET", f"/inbox/actors/{actor}/inbox")

    def message(self, object_id):
        return self._call("GET", f"/inbox/objects/{object_id}")

    def send(self, actor, to, content, summary=None, in_reply_to=None):
        note = {
            "type": "Note",
            "attributedTo": actor,
            "to": [t if "@" in t else f"{t}@local" for t in to],
            "content": content,
        }
        if summary:
            note["summary"] = summary
        if in_reply_to:
            note["inReplyTo"] = in_reply_to
        return self._call("POST", f"/inbox/actors/{actor}/outbox", note)

    def list_tasks(self):
        """Every board task, comments included."""
        return self._call("GET", "/board/tasks")

    def task(self, task_id):
        return self._call("GET", f"/board/tasks/{task_id}")

    def comment(self, author, task_id, text):
        return self._call(
            "POST", f"/board/tasks/{task_id}/comments", {"author": author, "text": text}
        )
