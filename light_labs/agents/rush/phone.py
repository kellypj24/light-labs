"""Rush and PJ's phone: texts through Messages, and waking the Mac for the next tick.

Texts go to PJ's own number, so every message Rush sends starts with PREFIX to tell it
apart from PJ's. Each text links to the draft on the remote page (remote.py), where PJ
sends or rejects it; Rush never reads Messages, so it needs no Full Disk Access.

The Mac sleeps between ticks. Each tick schedules the next wake with `pmset schedule
wake`, which needs root: one sudoers line limited to that command (see docs/rush-phone.md).
launchd runs the tick it missed on wake, under `caffeinate -i` so the Mac stays up until
the tick is done.
"""

import re
import subprocess
import time
from datetime import datetime, timedelta

PREFIX = "Rush:"
DRAFT_CHARS = 300
KEEP_NOTIFIED = 200

_SEND = """on run argv
  tell application "Messages"
    set svc to 1st account whose service type = iMessage
    send (item 2 of argv) to participant (item 1 of argv) of svc
  end tell
end run"""


def imessage(to, text, run=subprocess.run):
    run(["osascript", "-e", _SEND, to, text], check=True, capture_output=True, text=True)


def text_for(item, remote_url=None):
    """The text for one waiting draft: who and why, the draft, and the link to act on it."""
    who = item["context"].split(":", 1)[0][:60]
    where = item["target"].get("task_id") or "inbox"
    if item.get("escalate"):
        why = f"needs you ({item['escalate']})"
    elif item.get("held"):
        why = f"held: {'; '.join(item['held'])}"
    else:
        why = "waiting for approval"
    draft = item["draft"]
    if len(draft) > DRAFT_CHARS:
        draft = draft[:DRAFT_CHARS] + "…"
    link = f"\n\n{remote_url.rstrip('/')}/#{item['id']}" if remote_url else ""
    return f"{PREFIX} {who} on {where}, {why}.\n\n{draft}{link}"


def notify_pending(store, to, remote_url=None, send=imessage):
    """Text PJ once per draft waiting in the queue. Returns the ids texted."""
    state = store.load()
    notified = state.get("notified", [])
    texted = []
    for item in store.pending():
        if item["id"] in notified:
            continue
        send(to, text_for(item, remote_url))
        notified.append(item["id"])
        texted.append(item["id"])
    if texted:
        state["notified"] = notified[-KEEP_NOTIFIED:]
        store.save(state)
        store.journal(f"texted PJ about {', '.join(texted)}")
    return texted


_WAKE = re.compile(r"wake at (\d{1,2}/\d{1,2}/\d{2,4} \d{1,2}:\d{2}:\d{2})", re.IGNORECASE)


def scheduled_wakes(run=subprocess.run):
    out = run(["pmset", "-g", "sched"], capture_output=True, text=True).stdout
    wakes = []
    for stamp in _WAKE.findall(out):
        for fmt in ("%m/%d/%y %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
            try:
                wakes.append(datetime.strptime(stamp, fmt))
                break
            except ValueError:
                pass
    return wakes


def schedule_wake(minutes, run=subprocess.run, now=None):
    """Ask for a wake `minutes` from now unless one is already due by then.

    Returns (ok, detail). Never prompts: `sudo -n` fails when the sudoers line is missing."""
    now = now or datetime.now()
    at = now + timedelta(minutes=minutes)
    due = [w for w in scheduled_wakes(run) if now < w <= at]
    if due:
        return True, f"wake already due {min(due):%H:%M}"
    r = run(
        ["sudo", "-n", "/usr/bin/pmset", "schedule", "wake", at.strftime("%m/%d/%y %H:%M:%S")],
        capture_output=True,
        text=True,
    )
    if r.returncode:
        return False, (r.stderr or r.stdout).strip()
    return True, f"wake at {at:%H:%M}"


def wait_for_edge(check, timeout=90, every=5, sleep=time.sleep):
    """After a wake, Wi-Fi and Tailscale take a moment. True once `check()` stops raising."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            check()
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            sleep(every)
