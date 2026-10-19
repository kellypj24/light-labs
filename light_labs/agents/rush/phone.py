"""Rush and PJ's phone: texts through Messages, and waking the Mac for the next tick.

Texts go to PJ's own number, so every message Rush sends starts with PREFIX to tell it
apart from PJ's. At most one text per tick, and none in PJ's quiet hours (RUSH_QUIET_HOURS,
default midnight to 8am); that covers texts only, not Rush's work on the board. Each text
links to the remote page (remote.py), where PJ sends or rejects drafts; Rush never reads
Messages, so it needs no Full Disk Access.

The Mac sleeps between ticks. launchd runs the tick at the top of each hour
(StartCalendarInterval), and each tick schedules a wake for the next top of the hour with
`pmset schedule wake`, which needs root: one sudoers line limited to that command (see
docs/rush-phone.md). An interval timer drifts off the wakes; a clock-aligned one cannot.
The tick runs under `caffeinate -i` so the Mac stays up until it is done.
"""

import re
import subprocess
import time
from datetime import datetime, timedelta

PREFIX = "Rush:"
DRAFT_CHARS = 300
KEEP_NOTIFIED = 200
DIGEST_LINES = 5

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


def quiet(hours, now=None):
    """True inside PJ's quiet hours, given as "start-end" in local 24h hours ("0-8")."""
    if not hours:
        return False
    start, end = (int(h) for h in hours.split("-"))
    hour = (now or datetime.now()).hour
    return start <= hour < end if start < end else hour >= start or hour < end


def digest_for(items, remote_url=None):
    """One text for several waiting drafts, so a backlog never arrives as a burst."""
    lines = [
        f"- {i['context'].split(':', 1)[0][:40]} on {i['target'].get('task_id') or 'inbox'}"
        + (" (needs you)" if i.get("escalate") else "")
        for i in items[:DIGEST_LINES]
    ]
    more = len(items) - DIGEST_LINES
    if more > 0:
        lines.append(f"- and {more} more")
    link = f"\n\n{remote_url.rstrip('/')}/" if remote_url else ""
    return f"{PREFIX} {len(items)} drafts waiting.\n" + "\n".join(lines) + link


def notify_pending(
    store, to, remote_url=None, send=imessage, quiet_hours=None, now=None, send_item=None
):
    """At most one text per tick about drafts PJ hasn't heard about: the draft itself, or
    a digest when several are new. Nothing during quiet hours; they wait for the next tick
    after. Returns the ids covered."""
    if quiet(quiet_hours, now):
        return []
    state = store.load()
    notified = state.get("notified", [])
    new = [i for i in store.pending() if i["id"] not in notified]
    if not new:
        return []
    if len(new) == 1 and send_item:  # a channel with buttons (Telegram)
        send_item(new[0], text_for(new[0], remote_url))
    else:
        send(to, text_for(new[0], remote_url) if len(new) == 1 else digest_for(new, remote_url))
    texted = [i["id"] for i in new]
    state["notified"] = (notified + texted)[-KEEP_NOTIFIED:]
    store.save(state)
    store.journal(f"texted PJ about {', '.join(texted)}")
    return texted


def ping(store, to, until, ok, send=imessage, quiet_hours=None, now=None):
    """While testing (until a local ISO time), text PJ after every tick so he can see the
    Mac woke and the tick ran. Same quiet hours as drafts. True when a ping went out."""
    now = now or datetime.now()
    if not until or now >= datetime.fromisoformat(until) or quiet(quiet_hours, now):
        return False
    waiting = len(store.pending())
    send(
        to,
        f"{PREFIX} test ping {now:%-I:%M %p}. Awake; board check "
        f"{'ran' if ok else 'failed'}; {waiting} draft{'s' if waiting != 1 else ''} waiting.",
    )
    store.journal("sent PJ a test ping")
    return True


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


def next_slot(minutes, now):
    """The next clock-aligned slot: with 60, the next top of the hour. launchd runs the tick
    on the same boundary (StartCalendarInterval), so each wake lands on a tick."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = (now - midnight).total_seconds() // 60
    return midnight + timedelta(minutes=(elapsed // minutes + 1) * minutes)


def schedule_wake(minutes, run=subprocess.run, now=None):
    """Ask for a wake at the next slot unless one is already due by then.

    Returns (ok, detail). Never prompts: `sudo -n` fails when the sudoers line is missing."""
    now = now or datetime.now()
    at = next_slot(minutes, now)
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
