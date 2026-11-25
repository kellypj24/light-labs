"""The dashboard's loop: gather, draw, read a key.

Keys are read with os.read on the raw fd after select, never through sys.stdin's
buffer (a buffered read strands pasted or queued keys). ESC alone never quits: arrow
keys and every other escape sequence start with it. Pasted text is ignored whole
(bracketed paste), so a paste can't quit or tick a task.

Slow sources (Google Calendar, `gh`, Ollama) run on background threads and the frame
shows their last answer, so a refresh never waits on the network.
"""

import os
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from light_labs.core import heavy, monitor
from light_labs.dash import agenda, feed, labstate, render, review, sessions, tasks
from light_labs.training.calendar import TZ

LETTERS = "abcdefghijklmnopqrstuvwxyz"
LOCAL_EVERY = 5  # seconds between re-reads of local files
FEED_RECENT = timedelta(hours=24)  # what the RECENT section draws from
FEED_OPEN = timedelta(days=7)  # what `f` opens
CALENDAR_EVERY = 300
REVIEW_EVERY = 600
MODELS_EVERY = 60
ESC_WAIT = 0.05  # how long a lone ESC waits to become the start of a sequence
MAX_SEQUENCE = 32
PASTE_START, PASTE_END = b"200~", b"201~"


# --- keys


class Decoder:
    """Bytes from the terminal as key tokens: a printable ASCII character as itself,
    "esc" for ESC alone, "seq" for an escape sequence, "other" for anything else."""

    def __init__(self):
        self.pending = b""
        self.pasting = False

    def feed(self, data):
        buf, out, i = self.pending + data, [], 0
        self.pending = b""
        while i < len(buf):
            b = buf[i]
            if b == 0x1B:
                token, used = self._escape(buf, i)
                if used == 0:  # incomplete: wait for the rest
                    self.pending = buf[i:]
                    if len(self.pending) > MAX_SEQUENCE:
                        self.pending = b""
                    break
                i += used
            elif b < 0x80:
                token, i = (chr(b) if 0x20 <= b < 0x7F else "other"), i + 1
            else:  # UTF-8: one token for the whole character
                i += 1
                while i < len(buf) and 0x80 <= buf[i] < 0xC0:
                    i += 1
                token = "other"
            if token and not self.pasting:
                out.append(token)
        return out

    def _escape(self, buf, i):
        """(token, bytes used) for the escape at buf[i]; used == 0 when incomplete."""
        if i + 1 >= len(buf):
            return None, 0
        nxt = buf[i + 1]
        if nxt == 0x1B:
            return "esc", 1
        if nxt == ord("O"):  # SS3: one more byte
            return ("seq", 3) if i + 2 < len(buf) else (None, 0)
        if nxt != ord("["):
            return "seq", 2  # alt+key
        end = i + 2
        while end < len(buf) and not 0x40 <= buf[end] <= 0x7E:
            end += 1
        if end >= len(buf):
            return None, 0
        body = buf[i + 2 : end + 1]
        if body == PASTE_START:
            self.pasting = True
            return None, end + 1 - i
        if body == PASTE_END:
            self.pasting = False
            return None, end + 1 - i
        return "seq", end + 1 - i

    @property
    def lone_esc(self):
        return self.pending == b"\x1b" and not self.pasting

    def flush(self):
        """What a pause in input makes of the bytes held back: ESC alone is "esc". A
        sequence that has started is kept until its last byte arrives, however late,
        so its tail is never read as keys."""
        if not self.lone_esc:
            return []
        self.pending = b""
        return ["esc"]


@dataclass
class State:
    mode: str = "normal"  # or "pick": the next letter ticks a task
    message: str = ""
    letters: dict = field(default_factory=dict)  # letter -> Task, as displayed
    snapshot: tasks.Snapshot | None = None  # the read the letters came from
    events: list = field(default_factory=list)  # calendar rows, as displayed
    undo: list = field(default_factory=list)
    our_mtime: int | None = None  # the tasks file's mtime after the dashboard's last write
    jobs_open: bool = False  # the full job list, not the one-line count
    feed_open: bool = False  # the feed over the whole frame, not its last few lines


def press(state, key):
    """Apply one key to `state`; returns the effects for the loop to carry out."""
    if state.mode == "pick":
        state.mode = "normal"
        if key in state.letters:
            return [("check", state.letters[key])]
        state.message = "nothing checked"
        return []
    state.message = ""
    if key == "q":
        return [("quit",)]
    if key == "r":
        return [("refresh",)]
    if key == "R":
        return [("reload",)]
    if key == "u":
        return [("undo",)]
    if key == "j":
        state.jobs_open = not state.jobs_open
        return []
    if key == "f":
        state.feed_open = not state.feed_open
        return []
    if key == "x":
        if state.letters:
            state.mode = "pick"
        else:
            state.message = "no open tasks"
        return []
    if len(key) == 1 and key in "123456789":
        row = next((r for r in state.events if r["n"] == int(key)), None)
        if row is None:
            state.message = f"no row {key}"
        elif not row["url"]:
            state.message = f"row {key} has no link"
        else:
            return [("open", row["url"])]
    return []


def assign_letters(snapshot):
    """([(letter, task)] mine, [(letter, task)] waiting, {letter: task}). Tasks past the
    26th get no letter."""
    mine, waiting = tasks.mine(snapshot), tasks.waiting(snapshot)
    marks = iter(LETTERS)
    lettered = [(next(marks, ""), t) for t in [*mine, *waiting]]
    table = {letter: t for letter, t in lettered if letter}
    return lettered[: len(mine)], lettered[len(mine) :], table


def do_check(state, task):
    try:
        record = tasks.check(state.snapshot, task)
    except tasks.Stale as e:
        state.message = f"not checked: {e}"
    except (OSError, ValueError) as e:
        state.message = f"not checked: {describe(e)}"
    else:
        state.undo.append(record)
        state.our_mtime = record["mtime_ns"]
        state.message = f"checked: {task.text}  (u undoes)"


def do_undo(state):
    if not state.undo:
        state.message = "nothing to undo"
        return
    record = state.undo[-1]
    try:
        state.our_mtime = tasks.undo(record, state.our_mtime)
    except (tasks.Stale, OSError, ValueError) as e:
        state.undo.clear()  # the file is no longer as the dashboard left it
        state.message = f"not undone: {e if isinstance(e, tasks.Stale) else describe(e)}"
    else:
        state.undo.pop()
        state.message = f"unchecked: {record['text']}"


# --- background sources


class Poller:
    """Calls `fn` every `every` seconds on its own thread and keeps the last answer. A
    failure keeps the previous value and records the error."""

    def __init__(self, fn, every):
        self.fn, self.every = fn, every
        self.value, self.error, self.at = None, "", None
        self._lock, self._wake = threading.Lock(), threading.Event()

    def once(self):
        try:
            value = self.fn()
        except Exception as e:  # noqa: BLE001 - any failure costs only this section
            with self._lock:
                self.error = describe(e)
        else:
            with self._lock:
                self.value, self.error, self.at = value, "", datetime.now(UTC)

    def _loop(self):
        while True:
            self.once()
            self._wake.wait(self.every)
            self._wake.clear()

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def poke(self):
        self._wake.set()

    def get(self):
        with self._lock:
            return self.value, self.error, self.at


def describe(error):
    """An exception as one short line, without a command line or token in it."""
    if isinstance(error, agenda.NotSignedIn):
        return str(error)
    if isinstance(error, subprocess.CalledProcessError):
        tool = os.path.basename(str(error.cmd[0])) if error.cmd else "command"
        if tool == "security":
            # 44 is "item not found". Anything else (36: locked, or a session with no
            # access to the login keychain) says nothing about the sign-in.
            if error.returncode == 44:
                return "not signed in: run `lab google auth dash`"
            return f"Keychain could not be read (security exit {error.returncode})"
        return f"{tool} failed (exit {error.returncode})"
    if isinstance(error, subprocess.TimeoutExpired):
        return "timed out"
    code = getattr(error, "code", None)
    if code in (400, 401):
        return "sign-in expired: run `lab google auth dash`"
    return f"{type(error).__name__}: {error}"[:120]


def fetch_events():
    """Today's events with the day they are for, so a frame after midnight can tell."""
    day = datetime.now(TZ).date()
    return {"day": day, "events": agenda.fetch(day)}


def pollers():
    return {
        "events": Poller(fetch_events, CALENDAR_EVERY),
        "review": Poller(review.fetch, REVIEW_EVERY),
        "models": Poller(heavy.loaded_models, MODELS_EVERY),
    }


# --- the model


def _try(read, default, problems, name):
    try:
        return read()
    except Exception as e:  # noqa: BLE001 - one unreadable source costs only its section
        problems.append(f"{name}: {describe(e)}")
        return default


def gather(state, sources, now=None):
    """Everything the frame shows. Local files are read here; the slow sources are
    taken from their pollers. While a task is being picked, the task list is the one
    already on screen."""
    now = now or datetime.now(TZ)
    extra = []
    if state.mode != "pick" or state.snapshot is None:
        state.snapshot = _try(tasks.read, tasks.Snapshot(tasks.path(), None), extra, "tasks")
    mine, waiting, state.letters = assign_letters(state.snapshot)

    fetched, events_error, _ = sources["events"].get()
    events = None
    if fetched and fetched["day"] == now.date():
        events = fetched["events"]
    elif fetched:  # yesterday's answer: ask again, show nothing meanwhile
        sources["events"].poke()
    rows, review_error, review_at = sources["review"].get()
    models, _, _ = sources["models"].get()
    if events_error and not events_error.startswith("DASH_GOOGLE_ACCOUNT"):
        extra.append(f"calendar: {events_error}")
    if review_error:
        extra.append(f"github: {review_error}")

    agents = _try(labstate.agents, [], extra, "launchd")
    jobs = _try(labstate.dagster_jobs, [], extra, "dagster")
    notes = [n for n in (_try(lambda: labstate.heavy_job(now), None, extra, "heavy"),) if n]
    if models:
        shown = monitor.models_view(models, now)
        notes.append("ollama: " + ", ".join(monitor.model_line(x) for x in shown))
    queue_error = []
    feed_span = FEED_OPEN if state.feed_open else FEED_RECENT
    model = {
        "now": now,
        "mode": state.mode,
        "jobs_open": state.jobs_open,
        "feed_open": state.feed_open,
        "feed": _try(lambda: feed.events(now - feed_span, now), [], extra, "feed"),
        "message": state.message,
        "notes": [" · ".join(notes)] if notes else [],
        "sessions": _try(sessions.live, [], extra, "sessions"),
        "events": None if events is None else agenda.rows(events, now),
        "events_error": events_error,
        "training": _try(lambda: labstate.training_today(now.date()), None, extra, "training"),
        "queue": _try(lambda: labstate.queue(now), [], queue_error, "queue"),
        "queue_error": queue_error[0].partition(": ")[2] if queue_error else "",
        "tasks_mine": mine,
        "tasks_waiting": waiting,
        "tasks_note": str(state.snapshot.path).replace(str(os.path.expanduser("~")), "~", 1)
        + ("" if state.snapshot.mtime_ns is not None else " (no file yet)"),
        "review": rows,
        "review_error": review_error,
        "review_at": review_at,
        "agents": agents,
        "jobs": jobs,
        "evals": _try(labstate.evals, [], extra, "evals"),
    }
    model["problems"] = labstate.problems(now, agents, jobs, extra)
    state.events = model["events"] or []
    return model


# --- the loop

ENTER = "\033[?1049h\033[?25l\033[?2004h"  # alternate screen, no cursor, bracketed paste
LEAVE = "\033[?2004l\033[?25h\033[?1049l"


def draw(model, out=None):
    out = out or sys.stdout
    size = shutil.get_terminal_size((100, 40))
    try:
        # One column short: a character in the last column is cut off by some windows.
        lines = render.frame(model, size.columns - 1, size.lines, color=True)
    except Exception as e:  # noqa: BLE001 - a bad record must not end the dashboard
        lines = [render.clean(f"lab dash: could not draw: {describe(e)}"), "r retry  q quit"]
    out.write("\033[H" + "\033[K\n".join(lines) + "\033[K\033[J")
    out.flush()


def once(out=None):
    """One frame on stdout, the slow sources fetched first."""
    out = out or sys.stdout
    sources = pollers()
    threads = [threading.Thread(target=p.once) for p in sources.values()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    model = gather(State(), sources)
    cols = shutil.get_terminal_size((100, 40)).columns
    out.write("\n".join(render.frame(model, cols, color=out.isatty())) + "\n")


def follow(since="1d", once=False, out=None, sleep=time.sleep):
    """`lab feed`: the events since `since`, oldest first, then each new one as it is
    recorded. Plain lines, so it works in any pane or over ssh."""
    out = out or sys.stdout
    paint = render.Paint(out.isatty())
    start = datetime.now(TZ) - feed.span(since)
    seen = set()
    try:
        while True:
            for e in reversed(feed.events(start)):
                key = (e["at"], e["source"], e["text"])
                if key in seen:
                    continue
                seen.add(key)
                color = {"bad": "red", "good": "green"}.get(e["level"], "")
                stamp = f"{e['at'].astimezone(TZ):%a %d %b %H:%M}"
                source = render.pad(e["source"], 7)
                text = paint(render.clean(e["text"]), color)
                out.write(f"{paint(stamp, 'dim')}  {paint(source, 'dim')}  {text}\n")
            out.flush()
            if once:
                return
            sleep(LOCAL_EVERY)
    except KeyboardInterrupt:
        return


def run():
    import termios
    import tty

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.exit("lab dash needs a terminal; `lab dash --once` prints one frame")
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    state, decoder, sources = State(), Decoder(), pollers()
    for p in sources.values():
        p.start()
    reload, resumed = False, []

    def enter():
        tty.setcbreak(fd)
        sys.stdout.write(ENTER)
        sys.stdout.flush()

    def leave():
        sys.stdout.write(LEAVE)
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    def stop(signum, _frame):
        raise SystemExit(128 + signum)  # through the finally below

    def suspend(_signum, _frame):
        leave()
        os.kill(os.getpid(), signal.SIGSTOP)
        enter()  # running again
        resumed.append(True)

    handlers = {signal.SIGTERM: stop, signal.SIGHUP: stop, signal.SIGTSTP: suspend}
    previous = {sig: signal.signal(sig, fn) for sig, fn in handlers.items()}
    try:
        enter()
        due, size = 0.0, None
        while True:
            now = time.monotonic()
            if resumed:
                resumed.clear()
                due = 0.0
            if now >= due or size != shutil.get_terminal_size():
                size = shutil.get_terminal_size()
                draw(gather(state, sources))
                due = now + LOCAL_EVERY
            wait = ESC_WAIT if decoder.lone_esc else max(0.0, min(1.0, due - time.monotonic()))
            ready, _, _ = select.select([fd], [], [], wait)
            if ready:
                data = os.read(fd, 1024)
                if not data:  # the terminal went away
                    return
                keys = decoder.feed(data)
            else:
                keys = decoder.flush()
            for key in keys:
                for effect in press(state, key):
                    if effect[0] == "quit":
                        return
                    if effect[0] == "reload":
                        reload = True
                        return
                    if effect[0] == "refresh":
                        for p in sources.values():
                            p.poke()
                    elif effect[0] == "check":
                        do_check(state, effect[1])
                    elif effect[0] == "undo":
                        do_undo(state)
                    elif effect[0] == "open":
                        _open(effect[1])
                due = 0.0  # redraw after any key
    except KeyboardInterrupt:
        return
    finally:
        leave()
        for sig, fn in previous.items():
            signal.signal(sig, fn)
        if reload:
            os.execv(sys.executable, [sys.executable, *sys.orig_argv[1:]])


def _open(url):
    if url.startswith("https://"):
        subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
