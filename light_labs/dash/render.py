"""The dashboard's frame as lines of text. Pure: a model in, lines out.

Text from outside (event titles, PR titles, a session's last reply) is stripped of
control characters before it is drawn, so none of it can move the cursor or recolor
the terminal.
"""

import re
import unicodedata
from datetime import timedelta

from light_labs.dash import tasks as tasks_mod

CODES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "cyan": "36",
         "reverse": "7"}  # fmt: skip
ELLIPSIS = "…"
INDENT = "  "
GAP = "  "
MIN_FLEX = 12
NARROW = 80  # below this a side pane: the less useful columns are dropped


def clean(text):
    return "".join(
        " " if ch in "\t\n\r" else ch
        for ch in str(text)
        if ch in "\t\n\r" or unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co")
    )


def char_width(ch):
    if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


VS16 = "\ufe0f"  # emoji presentation: the character before it is drawn 2 wide


def cells(text):
    """(cluster, columns) for each drawn cell: a character with the zero-width
    characters that follow it."""
    out = []
    for ch in text:
        w = char_width(ch)
        if w == 0 and out:
            base, base_w = out[-1]
            out[-1] = (base + ch, 2 if ch == VS16 else base_w)
        else:
            out.append((ch, w))
    return out


def width(text):
    return sum(w for _, w in cells(text))


def clip(text, limit):
    """`text` cut to `limit` columns, ending in an ellipsis when cut."""
    if limit <= 0:
        return ""
    if width(text) <= limit:
        return text
    out, used = [], 0
    for cluster, w in cells(text):
        if used + w > limit - 1:
            break
        out.append(cluster)
        used += w
    return "".join(out) + ELLIPSIS


def _chunks(word, limit):
    """A word longer than a line, cut into pieces that fit."""
    out, part, used = [], "", 0
    for cluster, w in cells(word):
        if part and used + w > limit:
            out.append(part)
            part, used = "", 0
        part += cluster
        used += w
    return [*out, part]


def wrap(text, limit, max_lines):
    """`text` broken at spaces into at most `max_lines` lines of `limit` columns; the
    last line ends in an ellipsis when text is left over."""
    if limit <= 0 or max_lines <= 0:
        return [""]
    if max_lines == 1 or width(text) <= limit:
        return [clip(text, limit)]
    words = [piece for word in text.split() for piece in _chunks(word, limit)]
    lines, line = [], ""
    for i, word in enumerate(words):
        if not line:
            line = word
        elif width(line) + 1 + width(word) <= limit:
            line += " " + word
        elif len(lines) == max_lines - 1:
            return [*lines, clip(" ".join([line, *words[i:]]), limit)]
        else:
            lines.append(line)
            line = word
    return [*lines, line]


MD_LINK = re.compile(r"\[([^\]]*)\]\([^)\s]*\)?")
MD_MARKS = re.compile(r"\*\*|`|^#+ |(?<= )#+ |(?<= )[-*] ")


def plain(text):
    """Markdown as one line of prose: links keep their text, and emphasis, code and
    list marks are dropped."""
    return " ".join(MD_MARKS.sub("", MD_LINK.sub(r"\1", clean(text))).split())


def pad(text, to):
    return text + " " * max(0, to - width(text))


class Paint:
    def __init__(self, color=True):
        self.color = color

    def __call__(self, text, *styles):
        styles = [s for s in styles if s]
        if not self.color or not styles or not text:
            return text
        return f"\033[{';'.join(CODES[s] for s in styles)}m{text}\033[0m"


def table(rows, cols, paint, flex=None, wrap_to=1):
    """Rows of cells as aligned lines. A cell is text or (text, *styles). The `flex`
    column takes what is left of `cols`; its text wraps onto at most `wrap_to` lines,
    the later ones aligned under the first, and is clipped after that."""
    cells = [[(c, ()) if isinstance(c, str) else (c[0], tuple(c[1:])) for c in r] for r in rows]
    cells = [[(clean(text), styles) for text, styles in r] for r in cells]
    if not cells:
        return []
    count = max(len(r) for r in cells)
    widths = [max((width(r[i][0]) for r in cells if i < len(r)), default=0) for i in range(count)]
    if flex is not None and flex < count:
        others = sum(w for i, w in enumerate(widths) if i != flex)
        room = cols - len(INDENT) - others - len(GAP) * (count - 1)
        widths[flex] = max(MIN_FLEX, min(widths[flex], room))
    lines = []
    for r in cells:
        parts, more = [], []
        for i, (text, styles) in enumerate(r):
            if i == flex and wrap_to > 1:
                text, *rest = wrap(text, widths[i], wrap_to)
                under = len(INDENT) + sum(widths[:i]) + len(GAP) * i
                if under + widths[i] <= cols:  # else the column is already off the edge
                    more = [" " * under + paint(piece, *styles) for piece in rest]
            else:
                text = clip(text, widths[i])
            last = i == len(r) - 1
            parts.append(paint(text, *styles) + ("" if last else " " * (widths[i] - width(text))))
        lines.append(clip_line(INDENT + GAP.join(parts).rstrip(), cols))
        lines += [clip_line(line, cols) for line in more]
    return lines


def clip_line(line, cols):
    """A styled line cut to `cols` visible columns."""
    out, used, i = [], 0, 0
    while i < len(line):
        if line[i] == "\033":
            end = line.find("m", i)
            if end == -1:
                break
            out.append(line[i : end + 1])
            i = end + 1
            continue
        end = i + 1
        while end < len(line) and line[end] != "\033" and char_width(line[end]) == 0:
            end += 1
        w = width(line[i:end])
        if used + w > cols:
            out.append("\033[0m" if "\033" in line else "")
            break
        out.append(line[i:end])
        used += w
        i = end
    return "".join(out)


def ago(then, now):
    if then is None:
        return ""
    s = max(0, int((now - then).total_seconds()))
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h" if s < 86400 else f"{s // 86400}d"


def tokens(n):
    if n is None:
        return ""
    return f"{n / 1000:.0f}k" if n >= 1000 else str(n)


def heading(text, paint, note=""):
    return paint(text, "bold", "cyan") + (paint(f"  {clean(note)}", "dim") if note else "")


# --- sections


def _header(m, cols, paint):
    left = f"lab dash  {m['now']:%a %d %b %H:%M}"
    if m.get("mode") == "pick":
        keys = ["letter: check off", "any other key: cancel"]
    else:
        keys = ["r refresh", "1-9 open", "x check", "u undo", "j jobs", "R reload", "q quit"]
    hint = GAP.join(keys)
    space = cols - width(left) - width(hint)
    if space >= 2:
        lines = [paint(left, "bold") + " " * space + paint(hint, "dim")]
    else:
        lines, row = [paint(clip(left, cols), "bold")], ""
        for key in keys:
            if row and width(row) + len(GAP) + width(key) > cols:
                lines.append(paint(row, "dim"))
                row = ""
            row += (GAP if row else "") + key
        lines.append(paint(clip(row, cols), "dim"))
    if m.get("problems"):
        text = "! " + " · ".join(clean(p) for p in m["problems"])
        lines += [paint(line, "red", "bold") for line in wrap(text, cols, 3)]
    for note in m.get("notes") or []:
        lines.append(paint(clip(clean(note), cols), "dim"))
    if m.get("message"):
        lines.append(paint(clip(clean(m["message"]), cols), "yellow"))
    return lines


def _sessions(m, cols, paint):
    live = m.get("sessions") or []
    waiting = sum(s["waiting"] for s in live)
    lines = ["", heading("CLAUDE SESSIONS", paint, f"{waiting} waiting on you, {len(live)} live")]
    rows = []
    for s in live:
        turn = ("your turn", "yellow", "bold") if s["waiting"] else ("busy", "dim")
        dim = () if s["waiting"] else ("dim",)
        rows.append([
            turn,
            (ago(s["since"], m["now"]), *dim),
            (clip(clean(s["title"]), 48), *dim),
            *([(s["cwd"], "dim")] if cols >= NARROW else []),
            (tokens(s["context"]), "dim"),
        ])  # fmt: skip
    if not rows:
        return [*lines, INDENT + paint("none running", "dim")]
    # The last reply goes under its row at full width: beside it, it is a thin column.
    under = INDENT * 2
    for s, line in zip(live, table(rows, cols, paint, flex=2), strict=True):
        lines.append(line)
        reply = plain(s["reply"])
        if reply:
            lines += [under + paint(piece, "dim") for piece in wrap(reply, cols - len(under), 1)]
    return lines


def _today(m, cols, paint):
    lines = ["", heading("TODAY", paint, f"{m['now']:%A %d %B}")]
    t = m.get("training")
    if t:
        if t["rest"]:
            text = "training: rest day"
        else:
            bits = [t["title"] or t["type"], t["slot"], f"{t['items']} items" if t["items"] else ""]
            text = "training: " + "  ".join(b for b in bits if b)
        lines.append(INDENT + clip(clean(text), cols - len(INDENT)))
    events = m.get("events")
    if m.get("events_error"):
        lines.append(INDENT + paint(clip(f"calendar: {clean(m['events_error'])}", cols - 2), "red"))
    if events is None:
        if not m.get("events_error"):
            lines.append(INDENT + paint("calendar: loading", "dim"))
        return lines
    if not events:
        lines.append(INDENT + paint("nothing on the calendar", "dim"))
        return lines
    rows = []
    for e in events:
        style = ("bold",) if e["focus"] else ("dim",) if e["countdown"] == "done" else ()
        count_style = ("green", "bold") if e["countdown"] == "now" else style
        title = e["title"] + ("  (reply?)" if e["unanswered"] else "")
        rows.append([
            ("▸" if e["focus"] else " ", *style),
            (str(e["n"]) if e["n"] <= 9 else "", "dim"),
            (e["time"], *style),
            (e["countdown"], *count_style),
            (title, *style),
            (("join " if e["join"] else "") + e["calendar"], "dim"),
        ])  # fmt: skip
    return lines + table(rows, cols, paint, flex=4, wrap_to=2)


def _queue(m, cols, paint):
    rows = []
    for g in m.get("queue") or []:
        escalated = (f"{g['escalated']} escalated", "yellow") if g["escalated"] else ""
        oldest = f"oldest {ago(g['oldest'], m['now'])}" if g["oldest"] else ""
        rows.append([str(g["robot"]).title(), str(g["kind"]), f"{g['count']} waiting", escalated,
                     (oldest, "dim")])  # fmt: skip
    if m.get("queue_error"):
        rows.append([(f"queue: {m['queue_error']}", "red")])
    if not rows:
        return []
    return ["", heading("WAITING ON YOU FROM THE LAB", paint, "act in Telegram"), *table(
        rows, cols, paint
    )]  # fmt: skip


def _due(task, today):
    if task.due is None:
        return ("", "dim")
    style = {"overdue": "red", "soon": "yellow", "": "dim"}[tasks_mod.urgency(task, today)]
    return (f"{task.due:%a %d %b}", style)


def _tasks(m, cols, paint):
    today = m["now"].date()
    picking = m.get("mode") == "pick"
    key = ("yellow", "bold") if picking else ("dim",)
    lines = ["", heading("TASKS", paint, m.get("tasks_note", ""))]
    mine = m.get("tasks_mine") or []
    rows = [[(letter, *key), _due(t, today), t.text] for letter, t in mine]
    lines += table(rows, cols, paint, flex=2, wrap_to=3) or [INDENT + paint("nothing open", "dim")]
    waiting = m.get("tasks_waiting") or []
    if waiting:
        lines += ["", heading("WAITING ON OTHERS", paint)]
        rows, last = [], None
        for letter, t in waiting:
            who = t.who if t.who.casefold() != last else ""
            last = t.who.casefold()
            rows.append([(letter, *key), (who, "bold"), _due(t, today), t.text])
        lines += table(rows, cols, paint, flex=3, wrap_to=3)
    return lines


def _review(m, cols, paint):
    rows = m.get("review")
    age = m.get("review_at")
    note = f"fetched {ago(age, m['now'])} ago" if age else ""
    note = "fetched just now" if note == "fetched 0m ago" else note
    lines = ["", heading("REPO REVIEW QUEUE", paint, note)]
    if m.get("review_error"):
        lines.append(INDENT + paint(clip(f"github: {clean(m['review_error'])}", cols - 2), "red"))
    if rows is None:
        return lines if m.get("review_error") else [*lines, INDENT + paint("loading", "dim")]

    def quiet(row):
        return ("dim",) if row["kind"] == "canary" else ()

    styles = {"ci": ("red", "bold"), "pr": ("yellow",), "review": (), "issue": ("dim",),
              "canary": ("dim",)}  # fmt: skip
    table_rows = [
        [
            (r["kind"], *styles.get(r["kind"], ())),
            (r["repo"] + (f" #{r['number']}" if r["number"] else ""), *quiet(r)),
            (r["title"], *quiet(r)),
            (r["detail"], "dim"),
        ]
        for r in rows
    ]
    return lines + (
        table(table_rows, cols, paint, flex=2, wrap_to=2) or [INDENT + paint("clear", "dim")]
    )


def grid(label, items, cols, paint):
    """(name, state, ok) items in as many columns as fit, filled down each column, with
    `label` before the first row."""
    if not items:
        return []
    items = [(clean(n), clean(s), ok) for n, s, ok in items]
    lead = INDENT + pad(label, 7) + GAP
    between = " " * 4
    for across in range(len(items), 0, -1):
        down = -(-len(items) // across)
        columns = [items[i : i + down] for i in range(0, len(items), down)]
        sizes = [
            (max(width(n) for n, _, _ in col), max(width(s) for _, s, _ in col)) for col in columns
        ]
        total = sum(n + len(GAP) + s for n, s in sizes) + len(between) * (len(columns) - 1)
        if len(lead) + total <= cols or across == 1:
            break
    lines = []
    for r in range(down):
        parts = [
            pad(col[r][0], n) + GAP + paint(pad(col[r][1], s), "dim" if col[r][2] else "red")
            for col, (n, s) in zip(columns, sizes, strict=True)
            if r < len(col)
        ]
        start = lead if r == 0 else " " * len(lead)
        lines.append(clip_line((start + between.join(parts)).rstrip(), cols))
    return lines


def _jobs(m, cols, paint, compact):
    agents, jobs = m.get("agents") or [], m.get("jobs") or []
    if compact:
        counts = [
            f"{kind} {sum(r['ok'] for r in rows)}/{len(rows)} ok"
            for kind, rows in (("launchd", agents), ("dagster", jobs))
            if rows
        ]
        lines = ["", heading("JOBS", paint, " · ".join(counts))]
        failed = [(a["name"], a["state"], False) for a in agents if not a["ok"]]
        failed += [(j["name"], j["status"].lower(), False) for j in jobs if not j["ok"]]
        lines += table([[n, (s, "red")] for n, s, _ in failed], cols, paint)
    else:
        lines = ["", heading("JOBS", paint)]
        lines += grid("launchd", [(a["name"], a["state"], a["ok"]) for a in agents], cols, paint)
        ran = [
            (j["name"], j["status"].lower() + (f" {ago(j['at'], m['now'])} ago" if j["at"] else ""),
             j["ok"])
            for j in jobs
        ]  # fmt: skip
        lines += grid("dagster", ran, cols, paint)
    runs = m.get("evals") or []
    if runs:
        fresh = [r for r in runs if m["now"] - r["at"] <= timedelta(days=30)] or runs[:1]
        bits = []
        for r in fresh[:4]:
            score = f"{r['passed']}/{r['done']}" if r["passed"] is not None and r["done"] else "?"
            state = "" if r["status"] == "completed" else f" {r['status']}"
            bits.append(f"{r['stage']} {score}{state} ({ago(r['at'], m['now'])} ago)")
        lines.append(INDENT + paint(clip(clean("evals: " + " · ".join(bits)), cols - 2), "dim"))
    return lines


def _build(m, cols, paint, compact):
    lines = _header(m, cols, paint)
    lines += _sessions(m, cols, paint)
    lines += _today(m, cols, paint)
    lines += _queue(m, cols, paint)
    lines += _tasks(m, cols, paint)
    lines += _review(m, cols, paint)
    lines += _jobs(m, cols, paint, compact)
    return lines


def frame(m, cols=100, rows=None, color=True):
    """The whole dashboard. With `rows`, healthy jobs collapse to a count when the full
    frame is too tall, and what still doesn't fit is cut with a count of what's hidden."""
    paint = Paint(color)
    lines = _build(m, cols, paint, compact=not m.get("jobs_open"))
    if rows and len(lines) > rows:
        hidden = len(lines) - rows + 1
        lines = [*lines[: rows - 1], paint(f"… {hidden} more lines; enlarge the window", "dim")]
    return lines
