"""Workouts: the week's plan as a phone web app (`lab training app`).

Its own process, port and launchd job, apart from Rush's remote. It opens on today's
session; each set or item is a button that checks off, and a note box logs a note or
replans (the code `/note` and `/replan` run in Rush's chat).

Check-offs go to an append-only log (`training/checks.py`), keyed by day and exercise so
a replan keeps them. They add to Strong and Health, which stay the record of what was
trained.

Access is the remote's (`core/tailnet.py`): 127.0.0.1 behind `tailscale serve`, an allowed
tailnet login, this machine's Host, a per-process token on every form. Stdlib only; pages
render on the server and `/app.js` saves a check-off without a reload.
"""

import html
import json
import re
import secrets
import struct
import threading
import traceback
import zlib
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from light_labs.core.store import now
from light_labs.core.tailnet import LOOPBACK, refusal, tailnet_hosts, tailnet_login
from light_labs.training import deliver
from light_labs.training.checks import check, checks, item_key, plan, plan_days, units

NAME = "Workouts"
PORT = 8788
WORKING_REFRESH_S = 5
SAID_CLIP = 600
CSP = (
    "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; "
    "img-src 'self'; manifest-src 'self'; form-action 'self'; base-uri 'none'; "
    "frame-ancestors 'none'"
)
_WEEK = re.compile(r"\d{4}-W\d{2}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![A-Za-z0-9])_(.+?)_(?![A-Za-z0-9])")


def esc(text):
    return html.escape(str(text if text is not None else ""))


def md_html(text):
    """The Markdown the plans use: headings, bullets, **bold**, _italic_. For a week that
    has only its text (an imported note, or a plan from before the JSON was kept)."""

    def inline(s):
        return _ITALIC.sub(r"<i>\1</i>", _BOLD.sub(r"<b>\1</b>", esc(s)))

    out, in_list = [], False
    for line in text.splitlines():
        line = line.strip()
        item = line.startswith("- ")
        if in_list and not item:
            out.append("</ul>")
        if item and not in_list:
            out.append("<ul>")
        in_list = item
        if item:
            out.append(f"<li>{inline(line[2:])}</li>")
        elif line.startswith("#"):
            out.append(f"<h3>{inline(line.lstrip('#').strip())}</h3>")
        elif line and not line.startswith("<!--"):
            out.append(f"<p>{inline(line)}</p>")
    return "\n".join(out + (["</ul>"] if in_list else []))


# --- plans and check-offs


def week_days(key):
    monday = date.fromisocalendar(int(key[:4]), int(key[6:]), 1)
    return [monday + timedelta(days=i) for i in range(7)]


def progress(day, done):
    """(units done, units in the day) for one plan day."""
    items = day.get("items", [])
    total = sum(units(i) for i in items)
    got = sum(
        len({n for n in done.get((day["date"], item_key(i)), ()) if n <= units(i)}) for i in items
    )
    return got, total


# --- the icon: drawn here so the app has no binary file in the repo

ACCENT_RGB = (217, 72, 15)


def icon_png(size=180):
    """A white dumbbell on the accent color, for the phone's home screen."""

    def white(x, y):
        u, v = x / size, y / size
        bar = 0.22 <= u <= 0.78 and 0.47 <= v <= 0.53
        inner = (0.26 <= u <= 0.34 or 0.66 <= u <= 0.74) and 0.30 <= v <= 0.70
        outer = (0.17 <= u <= 0.24 or 0.76 <= u <= 0.83) and 0.37 <= v <= 0.63
        return bar or inner or outer

    rows = b"".join(
        b"\x00"
        + b"".join(b"\xff\xff\xff" if white(x, y) else bytes(ACCENT_RGB) for x in range(size))
        for y in range(size)
    )

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    head = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", head)
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


MANIFEST = json.dumps(
    {
        "name": NAME,
        "short_name": NAME,
        "start_url": "/",
        "display": "standalone",
        "background_color": "#16130f",
        "theme_color": "#d9480f",
        "icons": [{"src": "/icon.png", "sizes": "180x180", "type": "image/png"}],
    }
)

STYLE = """
:root { --bg:#fbf7f2; --fg:#1d1a16; --muted:#75695c; --card:#fff; --line:#e8dfd3;
  --accent:#d9480f; --on:#2f7d32; --on-fg:#fff; }
@media (prefers-color-scheme: dark) { :root { --bg:#16130f; --fg:#f1ebe2; --muted:#a2978a;
  --card:#211d18; --line:#3a332b; --accent:#ff8a4c; --on:#6fbf73; --on-fg:#10200f; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:17px/1.45 -apple-system, system-ui, sans-serif; -webkit-text-size-adjust:100%; }
header { background:var(--accent); color:#fff; padding:14px 16px;
  padding-top:calc(14px + env(safe-area-inset-top)); display:flex; align-items:baseline; }
header a { color:#fff; text-decoration:none; }
header b { font-size:20px; letter-spacing:.02em; margin-right:auto; }
a { color:var(--accent); text-decoration:none; }
main { padding:12px 16px 56px; max-width:640px; margin:0 auto; }
.weeknav { display:flex; justify-content:space-between; align-items:baseline;
  font-size:14px; margin:4px 0 10px; }
.weeknav b { font-size:15px; }
.strip { display:grid; grid-template-columns:repeat(7, 1fr); gap:6px; margin-bottom:16px; }
.chip { display:block; text-align:center; padding:6px 0 8px; border-radius:10px;
  border:1px solid var(--line); background:var(--card); color:var(--fg); font-size:12px; }
.chip b { display:block; font-size:17px; }
.chip i { display:block; height:4px; width:16px; margin:4px auto 0; border-radius:2px;
  background:var(--line); }
.chip.rest { color:var(--muted); background:none; }
.chip.rest i { visibility:hidden; }
.chip.part i { background:var(--accent); }
.chip.done i { background:var(--on); }
.chip.today { border-color:var(--accent); }
.chip.sel { background:var(--accent); border-color:var(--accent); color:#fff; }
.chip.sel i { background:rgba(255,255,255,.45); }
.chip.sel.done i { background:#fff; }
h1 { font-size:24px; margin:0; }
h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted);
  margin:28px 0 8px; }
.meta { color:var(--muted); font-size:14px; }
.count { float:right; font-size:14px; color:var(--muted); padding-top:8px; }
.count.done { color:var(--on); font-weight:600; }
.item { background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:12px; margin:12px 0; }
.item .dose { color:var(--muted); font-size:15px; }
.sets { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
.sets form { margin:0; }
.sets button { min-width:52px; height:48px; padding:0 14px; border-radius:24px;
  border:2px solid var(--line); background:none; color:var(--fg); font:600 17px inherit; }
.sets button.on { background:var(--on); border-color:var(--on); color:var(--on-fg); }
details { margin:12px 0; }
summary { color:var(--muted); font-size:14px; cursor:pointer; }
details p { margin:8px 0; font-size:15px; }
textarea { width:100%; min-height:72px; font:16px/1.4 inherit; padding:10px;
  border:1px solid var(--line); border-radius:10px; background:var(--card); color:var(--fg); }
.row { display:flex; gap:8px; margin-top:8px; flex-wrap:wrap; }
.row button { font:600 15px inherit; padding:10px 16px; border-radius:10px;
  border:1px solid var(--line); background:var(--card); color:var(--fg); }
.row button.go { background:var(--accent); border-color:var(--accent); color:#fff; }
.said { border:1px solid var(--line); border-left:4px solid var(--accent); border-radius:8px;
  padding:10px 12px; margin:0 0 14px; font-size:15px; white-space:pre-wrap; }
"""

# Saves a check-off without a reload; without it each button is a plain form post.
APP_JS = """document.addEventListener("submit", async (e) => {
  const form = e.target;
  if (!form.matches(".sets form")) return;
  e.preventDefault();
  const button = form.querySelector("button");
  const done = form.elements.done;
  button.disabled = true;
  try {
    const r = await fetch("/check", {
      method: "POST", body: new URLSearchParams(new FormData(form)),
      headers: {"X-Workouts": "1"}, credentials: "same-origin",
    });
    if (!r.ok) throw new Error(r.status);
    const state = await r.json();
    button.classList.toggle("on", done.value === "1");
    done.value = done.value === "1" ? "0" : "1";
    const count = document.getElementById("count");
    count.textContent = state.text;
    count.classList.toggle("done", state.done === state.total);
    const chip = document.querySelector(".chip.sel");
    chip.classList.toggle("done", state.done === state.total);
    chip.classList.toggle("part", state.done > 0 && state.done < state.total);
  } catch (err) {
    location.reload();
  } finally {
    button.disabled = false;
  }
});
"""


def shell(title, body, refresh=None):
    again = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="{NAME}">
<meta name="theme-color" content="#d9480f">
<link rel="apple-touch-icon" href="/icon.png"><link rel="icon" href="/icon.png">
<link rel="manifest" href="/manifest.webmanifest">{again}
<title>{esc(title)}</title><style>{STYLE}</style></head><body>
<header><b><a href="/">{NAME}</a></b><a href="/">Today</a></header>
<main>{body}</main><script src="/app.js"></script></body></html>"""


def count_text(got, total):
    return "Session done" if total and got == total else f"{got} of {total} done"


def dose(item):
    """'4 × 5 @ 60 lb' for a lift; '' for a text item."""
    if "exercise" not in item:
        return ""
    out = f"{item.get('sets', '?')} × {item.get('reps', '?')}"
    return out + (f" @ {item['load_lb']:g} lb" if item.get("load_lb") else "")


class App:
    """State shared by request handlers."""

    def __init__(self, allowed=(), hosts=(), var=None, clock=None, parser=None, planner=None):
        self.allowed = set(allowed)
        self.hosts = LOOPBACK | {h.lower() for h in hosts if h}
        self.var = var  # var/; tests point it elsewhere
        self.clock = clock or datetime.now  # tests fix the day and stay out of work hours
        self.parser, self.planner = parser, planner  # tests stand in for the models
        self.token = secrets.token_urlsafe(16)
        self.working = threading.Lock()
        self.doing = None  # what the background job is doing, while it runs
        self.said = []  # what the last job reported, shown until the next one

    def today(self):
        return self.clock().date()

    # --- notes and replans, off the request thread: a replan takes about a minute
    def hear(self, _, text):
        """`deliver`'s send: keep the reading or the outcome, not the plan's own text."""
        first = text.split("\n\n", 1)[0].strip()
        if first and not first.startswith(("**", "#")):
            self.said.append(first[:SAID_CLIP])

    def start(self, doing, job):
        """Run `job` in the background; False when one is already running."""
        if not self.working.acquire(blocking=False):
            return False
        self.doing, self.said = doing, []

        def run():
            try:
                job()
            except Exception as e:  # noqa: BLE001 - shown on the page; details in the log
                traceback.print_exc()
                self.said.append(f"That failed: {e}")
            finally:
                self.doing = None
                self.working.release()

        threading.Thread(target=run, daemon=True).start()
        return True

    def note(self, action, text):
        """The note box: 'note', 'replan' (with or without text) or 'undo'."""
        text = text.strip()
        if action == "undo":
            return self.start(
                "Dropping the last note",
                lambda: deliver.unnote(self.hear, now=self.clock(), var=self.var),
            )
        if action == "replan" and not text:
            return self.start(
                "Replanning; about a minute",
                lambda: deliver.replan(self.hear, self.clock(), self.planner, self.var),
            )
        if not text:
            return False
        replan = action == "replan"
        return self.start(
            "Reading the note, then replanning; about a minute" if replan else "Reading the note",
            lambda: deliver.note(
                text,
                self.hear,
                now=self.clock(),
                var=self.var,
                parser=self.parser,
                planner=self.planner,
                then_replan=replan,
            ),
        )

    # --- pages
    def hidden(self, **fields):
        fields = {"token": self.token, **fields}
        return "".join(
            f'<input type="hidden" name="{k}" value="{esc(v)}">' for k, v in fields.items()
        )

    def strip(self, days, shown, picked, done):
        chips = []
        for d in days:
            day = shown.get(d.isoformat())
            cls = ["chip"]
            if day is None or day.get("rest"):
                cls.append("rest")
            else:
                got, total = progress(day, done)
                cls += ["done"] if total and got == total else ["part"] if got else []
            cls += ["today"] if d == self.today() else []
            cls += ["sel"] if d == picked else []
            chips.append(
                f'<a class="{" ".join(cls)}" href="/d/{d.isoformat()}">{d:%a}<b>{d.day}</b><i></i></a>'
            )
        return f'<nav class="strip">{"".join(chips)}</nav>'

    def session(self, day, done):
        """One day's card: what to do, a button per set, and the planner's reason."""
        d = date.fromisoformat(day["date"])
        why = (
            f"<details><summary>Why this session</summary><p>{esc(day['why'])}</p></details>"
            if day.get("why")
            else ""
        )
        if day.get("rest"):
            return (
                f'<h1>Rest</h1><p class="meta">{d:%A, %b} {d.day}</p><p>{esc(day.get("why"))}</p>'
            )
        got, total = progress(day, done)
        slot = "–".join(day["slot"]) if day.get("slot") else ""
        where = "outdoor" if day.get("outdoor") else ""
        meta = " · ".join(x for x in (f"{d:%A, %b} {d.day}", slot, where) if x)
        cards = []
        for item in day.get("items", []):
            key, n_units = item_key(item), units(item)
            have = done.get((day["date"], key), set())
            buttons = "".join(
                '<form method="post" action="/check">'
                + self.hidden(date=day["date"], item=key, n=n, done=0 if n in have else 1)
                + f'<button class="{"on" if n in have else ""}">'
                + (str(n) if "exercise" in item else "Done")
                + "</button></form>"
                for n in range(1, n_units + 1)
            )
            name = esc(item.get("exercise") or item.get("text"))
            cards.append(
                f'<div class="item"><div>{name}</div><div class="dose">{esc(dose(item))}</div>'
                f'<div class="sets">{buttons}</div></div>'
            )
        cls = "count done" if total and got == total else "count"
        return (
            f'<span id="count" class="{cls}">{count_text(got, total)}</span>'
            f'<h1>{esc(day.get("title"))}</h1><p class="meta">{esc(meta)}</p>'
            + "".join(cards)
            + why
        )

    def week_note(self, whole):
        """The week's one-line summary and the planner's cue, folded away."""
        s = whole.get("summary") or {}
        rows = [
            ("", whole.get("glance")),
            ("Week", s.get("split")),
            ("Progressed", s.get("progressed")),
            ("Cue", s.get("cue")),
        ]
        body = "".join(f"<p>{f'<b>{k}:</b> ' if k else ''}{esc(v)}</p>" for k, v in rows if v)
        return f"<details><summary>This week</summary>{body}</details>" if body else ""

    def note_box(self, back):
        if self.doing:
            return f'<h2>Notes</h2><p class="meta">{esc(self.doing)}…</p>'
        return (
            '<h2>Notes</h2><form method="post" action="/note">'
            + self.hidden(back=back)
            + '<textarea name="text" placeholder="dentist Thu 3-5 · mowed 2h yesterday · sick today"></textarea>'
            '<div class="row"><button class="go" name="action" value="note">Log note</button>'
            '<button name="action" value="replan">Replan</button>'
            '<button name="action" value="undo">Undo last note</button></div></form>'
            '<p class="meta">Replan redoes the rest of this week, around the note if there is one.</p>'
        )

    def day_page(self, picked):
        """The week around `picked` and that day's session."""
        key = deliver.week_key(picked)
        days = week_days(key)
        whole = plan(key, self.var)
        shown = plan_days(whole)
        weeks = deliver.weeks(self.var)
        done = checks(self.var)
        before, after = (deliver.week_key(days[0] + timedelta(days=n)) for n in (-7, 7))
        nav = (
            f'<div class="weeknav"><a href="/w/{before}">‹ {before[5:]}</a>'
            f"<b>{days[0]:%b} {days[0].day} – {days[6]:%b} {days[6].day}</b>"
            f'<a href="/w/{after}">{after[5:]} ›</a></div>'
        )
        said = "".join(f'<div class="said">{esc(s)}</div>' for s in self.said)
        if whole:
            day = shown.get(picked.isoformat())
            body = self.strip(days, shown, picked, done) + (
                self.session(day, done) if day else '<p class="meta">Nothing planned this day.</p>'
            )
            body += self.week_note(whole)
        elif key in weeks:  # text only: nothing to check off
            body = md_html(weeks[key].read_text())
        else:
            body = f'<p class="meta">No plan for {key} yet.</p>'
        body = said + nav + body + self.note_box(f"/d/{picked.isoformat()}")
        return shell(NAME, body, refresh=WORKING_REFRESH_S if self.doing else None)

    def week_page(self, key):
        """A week opens on today when it holds today, else on its Monday."""
        days = week_days(key)
        return self.day_page(self.today() if self.today() in days else days[0])


def handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # one line per request on stdout
            print(f"{now()} {self.command} {self.path} {args[1] if len(args) > 1 else ''}")

        def _allowed(self):
            why = refusal(self.headers, app.hosts, app.allowed)
            if why:
                self._send(403, shell("Not allowed", f"<p>{why}</p>"))
            return why is None

        def _send(self, code, body, location=None, ctype="text/html; charset=utf-8", cache=None):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            if location:
                self.send_header("Location", location)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache or "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _missing(self):
            self._send(404, shell("Not found", "<p>Not found.</p>"))

        def do_GET(self):
            if not self._allowed():
                return
            parts = urlparse(self.path).path.strip("/").split("/")
            try:
                if parts == [""]:
                    return self._send(200, app.day_page(app.today()))
                if len(parts) == 2 and parts[0] == "d" and _DATE.fullmatch(parts[1]):
                    return self._send(200, app.day_page(date.fromisoformat(parts[1])))
                if len(parts) == 2 and parts[0] == "w" and _WEEK.fullmatch(parts[1]):
                    return self._send(200, app.week_page(parts[1]))
            except ValueError:  # 2026-02-31, 2026-W99
                return self._missing()
            if parts == ["app.js"]:
                return self._send(200, APP_JS, ctype="text/javascript; charset=utf-8")
            if parts == ["icon.png"]:
                return self._send(200, icon_png(), ctype="image/png", cache="max-age=86400")
            if parts == ["manifest.webmanifest"]:
                return self._send(200, MANIFEST, ctype="application/manifest+json")
            self._missing()

        def do_POST(self):
            if not self._allowed():
                return
            length = int(self.headers.get("Content-Length") or 0)
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
            if not secrets.compare_digest(form.get("token", ""), app.token):
                return self._send(403, shell("Stale page", "<p>Reload and try again.</p>"))
            path = urlparse(self.path).path
            if path == "/check":
                return self._check(form)
            if path == "/note":
                app.note(form.get("action", ""), form.get("text", ""))
                back = form.get("back", "")
                ok = back.startswith("/d/") and _DATE.fullmatch(back[3:])
                return self._send(303, "", location=back if ok else "/")
            self._send(400, shell("Bad request", "<p>Nothing to do.</p>"))

        def _check(self, form):
            day = form.get("date", "")
            try:
                check(
                    day,
                    form.get("item", ""),
                    int(form.get("n", "")),
                    form.get("done") == "1",
                    app.var,
                )
            except ValueError:
                return self._send(400, shell("Bad request", "<p>No such set.</p>"))
            if self.headers.get("X-Workouts") != "1":  # no script: back to the day
                return self._send(303, "", location=f"/d/{day}")
            week = plan_days(plan(deliver.week_key(date.fromisoformat(day)), app.var))
            got, total = progress(week[day], checks(app.var))
            state = {"done": got, "total": total, "text": count_text(got, total)}
            self._send(200, json.dumps(state), ctype="application/json")

    return Handler


def serve(host="127.0.0.1", port=PORT, allowed=None):
    app = App(allowed=allowed or [tailnet_login()], hosts=tailnet_hosts())
    server = ThreadingHTTPServer((host, port), handler(app))
    print(f"{NAME} on http://{host}:{port} for {sorted(app.allowed)}")
    server.serve_forever()
