"""PJ's tasks: checkbox lines in one markdown file (DASH_TASKS, default ~/tasks/tasks.md).

    - [ ] renew the car registration (2026-12-01)     mine, due date optional
    - [ ] [[Ketan]] send the tailnet key              waiting on Ketan

The only write the dashboard makes is one checkbox, and only when the whole line still
reads as it did when it was shown and the file has not been modified since it was read.
A mismatch writes nothing.
"""

import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

OPEN, DONE = "- [ ] ", "- [x] "
LINE = re.compile(r"^\s*- \[ \] (\S.*?)\s*$")
WHO = re.compile(r"^\[\[([^\]]+)\]\]\s*(.*)$")
DUE = re.compile(r"\s*\((\d{4}-\d{2}-\d{2})\)$")


def path():
    return Path(os.environ.get("DASH_TASKS") or Path.home() / "tasks" / "tasks.md")


class Stale(RuntimeError):
    """The file is not what was read; nothing was written."""


@dataclass(frozen=True)
class Task:
    line_no: int  # 0-based
    raw: str  # the whole line, without its newline
    text: str
    who: str | None = None
    due: date | None = None


@dataclass(frozen=True)
class Snapshot:
    path: Path
    mtime_ns: int | None  # None: no file
    tasks: tuple = ()


def parse_line(line_no, raw):
    m = LINE.match(raw)
    if not m:
        return None
    text, who, due = m.group(1), None, None
    if w := WHO.match(text):
        who, text = w.group(1).strip(), w.group(2)
    if d := DUE.search(text):
        try:
            due = date.fromisoformat(d.group(1))
        except ValueError:
            due = None
        else:
            text = text[: d.start()]
    return Task(line_no, raw, text.strip(), who, due)


def read(p=None):
    p = p or path()
    try:
        with p.open(encoding="utf-8", newline="") as f:
            mtime = os.fstat(f.fileno()).st_mtime_ns
            lines = f.read().splitlines()
    except FileNotFoundError:
        return Snapshot(p, None)
    tasks = (parse_line(i, raw) for i, raw in enumerate(lines))
    return Snapshot(p, mtime, tuple(t for t in tasks if t))


def _by_due(task):
    return (task.due is None, task.due or date.max, task.line_no)


def mine(snapshot):
    return sorted((t for t in snapshot.tasks if not t.who), key=_by_due)


def waiting(snapshot):
    """Tasks waiting on someone else, grouped by person, people in file order."""
    order = {}
    for t in snapshot.tasks:
        if t.who:
            order.setdefault(t.who.casefold(), len(order))
    return sorted(
        (t for t in snapshot.tasks if t.who),
        key=lambda t: (order[t.who.casefold()], *_by_due(t)),
    )


def urgency(task, today):
    if task.due is None:
        return ""
    if task.due < today:
        return "overdue"
    return "soon" if task.due <= today + timedelta(days=1) else ""


def swap(p, line_no, expect, replacement, mtime_ns):
    """Replace line `line_no` with `replacement` if it is exactly `expect` and the file is
    unmodified since `mtime_ns`. Returns the new mtime_ns; raises Stale and writes nothing
    otherwise. A symlink is followed: its target is rewritten and the link stays."""
    p = Path(os.path.realpath(p))
    try:
        with p.open(encoding="utf-8", newline="") as f:
            before = os.fstat(f.fileno())
            lines = f.read().splitlines(keepends=True)
    except FileNotFoundError:
        raise Stale(f"{p.name} is gone") from None
    except UnicodeDecodeError:
        raise Stale(f"{p.name} is no longer UTF-8 text") from None
    if before.st_mtime_ns != mtime_ns:
        raise Stale(f"{p.name} changed on disk")
    if line_no >= len(lines):
        raise Stale(f"{p.name} is shorter than it was")
    body = lines[line_no].rstrip("\r\n")
    if body != expect:
        raise Stale("the line no longer matches")
    lines[line_no] = replacement + lines[line_no][len(body) :]
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write("".join(lines))
        os.chmod(tmp, before.st_mode & 0o7777)
        if p.stat().st_mtime_ns != mtime_ns:  # changed while this ran
            raise Stale(f"{p.name} changed on disk")
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return p.stat().st_mtime_ns


def checked(raw):
    """The line with its box ticked."""
    return raw.replace(OPEN, DONE, 1)


def check(snapshot, task):
    """Tick `task`'s box. Returns what undo() needs."""
    done = checked(task.raw)
    mtime = swap(snapshot.path, task.line_no, task.raw, done, snapshot.mtime_ns)
    return {"path": snapshot.path, "line_no": task.line_no, "was": task.raw, "now": done,
            "mtime_ns": mtime, "text": task.text}  # fmt: skip


def undo(record, mtime_ns=None):
    """Put a ticked line back; only while the file is as the dashboard's last write left
    it (`mtime_ns`, default: the tick's own write)."""
    mtime_ns = record["mtime_ns"] if mtime_ns is None else mtime_ns
    return swap(record["path"], record["line_no"], record["now"], record["was"], mtime_ns)
