"""Rush's remote: a phone-sized web page for the approval queue and the board.

Served on 127.0.0.1 and published to the tailnet only with `tailscale serve`, which tells
us who is asking in the Tailscale-User-Login header. Requests without an allowed login are
refused, so the page is PJ's alone even on a shared tailnet. Forms carry a per-process
token against cross-site posts.

Stdlib only: http.server, html.escape. Pages render on the server; no JavaScript.
"""

import html
import json
import re
import secrets
import subprocess
import threading
from argparse import Namespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from light_labs.agents.rush.heartbeat import post
from light_labs.core.agentnet import Client
from light_labs.core.store import now

PJ_SIGNOFF = "— PJ (via pj_agent)"
# Board items worth showing PJ: anything naming him, Rush or the actor.
INTEREST = re.compile(r"\b(rush|pj_agent|pj-agent|DLN-100|PJ)\b", re.IGNORECASE)
BOARD_TASKS = 25
JOURNAL_LINES = 15
CLIP = 600


def tailnet_login():
    """This machine's Tailscale login, the default allowed user."""
    out = subprocess.run(
        ["tailscale", "status", "--json"], capture_output=True, text=True, check=True
    ).stdout
    d = json.loads(out)
    return d["User"][str(d["Self"]["UserID"])]["LoginName"]


def esc(text, clip=None):
    text = text or ""
    if clip and len(text) > clip:
        text = text[:clip] + "…"
    return html.escape(text)


def board_view(tasks, actor, limit=BOARD_TASKS):
    """Tasks that name PJ, Rush or the actor in the title, description or a comment,
    newest activity first, each with its latest comment."""
    hits = []
    for t in tasks:
        comments = t.get("comments") or []
        text = " ".join(
            [t.get("title", ""), t.get("description") or ""]
            + [c.get("text") or "" for c in comments]
        )
        if INTEREST.search(text):
            hits.append(t)
    hits.sort(key=lambda t: t.get("updatedAt") or "", reverse=True)
    return hits[:limit]


STYLE = """
:root { --bg:#fafaf7; --fg:#1c1c1a; --muted:#6b6b66; --card:#fff; --line:#e3e2dc;
  --accent:#1f5fbf; --warn:#b4541a; --ok:#2e7d32; }
@media (prefers-color-scheme: dark) { :root { --bg:#141413; --fg:#ecebe6; --muted:#9a9993;
  --card:#1e1e1c; --line:#33322f; --accent:#7aa7ff; --warn:#f0a060; --ok:#7bc47f; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:16px/1.45 -apple-system, system-ui, sans-serif; }
header { position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line);
  padding:12px 16px; display:flex; flex-wrap:wrap; gap:4px 16px; align-items:baseline; }
header b { margin-right:auto; }
a { color:var(--accent); text-decoration:none; }
main { padding:12px 16px 48px; max-width:720px; margin:0 auto; }
h2 { font-size:15px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted);
  margin:24px 0 8px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:12px; margin:0 0 12px; }
.meta { color:var(--muted); font-size:13px; }
.tag { font-size:12px; padding:1px 6px; border-radius:6px; border:1px solid var(--warn);
  color:var(--warn); }
pre, .ctx { white-space:pre-wrap; word-wrap:break-word; font:13px/1.4 ui-monospace, monospace;
  margin:6px 0; }
textarea, input[type=text] { width:100%; font:15px/1.4 inherit; padding:8px;
  border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--fg); }
textarea { min-height:140px; }
.row { display:flex; gap:8px; margin-top:8px; flex-wrap:wrap; }
button { font:15px inherit; padding:10px 14px; border-radius:8px; border:1px solid var(--line);
  background:var(--card); color:var(--fg); }
button.go { background:var(--accent); border-color:var(--accent); color:#fff; }
.flash { padding:10px 12px; border-radius:8px; border:1px solid var(--ok); margin:12px 0; }
.strip { display:flex; height:12px; border-radius:3px; overflow:hidden;
  background:var(--line); }
.strip span { display:block; height:100%; }
.week { display:grid; grid-template-columns:96px minmax(0,1fr) 48px; column-gap:8px;
  align-items:center; margin:6px 0; font-size:13px; }
.week > :nth-child(3) { text-align:right; }
.week > :nth-child(4) { grid-column:2 / 4; font-size:12px; }
.week .name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.legend { display:flex; flex-wrap:wrap; gap:4px 12px; font-size:12px; color:var(--muted); }
.legend i { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:4px; }
details > summary { list-style:none; cursor:pointer; }
details > summary::-webkit-details-marker { display:none; }
details > summary .name::before { content:"▸ "; color:var(--muted); }
details[open] > summary .name::before { content:"▾ "; }
details .week .name { padding-left:12px; }
"""


def page(title, body, flash=None):
    note = f'<div class="flash">{esc(flash)}</div>' if flash else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title><style>{STYLE}</style></head><body>
<header><b>Rush</b><a href="/">Queue</a><a href="/mail">Mail</a><a href="/board">Board</a>
<a href="/inbox">Inbox</a><a href="/usage">Usage</a>
</header><main>{note}{body}</main></body></html>"""


class Remote:
    """State shared by request handlers: the store, edge client, and the tick lock."""

    def __init__(self, store, rush, client=None, allowed=(), tick=None):
        self.store, self.rush = store, rush
        self.client = client or Client()
        self.allowed = set(allowed)
        self.token = secrets.token_urlsafe(16)
        self.tick = tick  # callable running one heartbeat
        self.usage_db = None  # var/lab.duckdb; tests point it elsewhere
        self.ticking = threading.Lock()

    # --- actions
    def approve(self, item_id, text):
        item = self.store.get(item_id)
        if text is not None and text.strip() != item["draft"].strip():
            item["draft"] = text.strip()
            self.store.update(item_id, draft=item["draft"])
        result = post(self.client, self.rush.ACTOR, item)
        self.store.resolve(item_id, "sent", result_id=result.get("id"))
        self.store.journal(f"sent {item_id} ({item['kind']}) from the remote")

    def reject(self, item_id, reason):
        self.store.resolve(item_id, "rejected", reason=reason or None)
        self.store.journal(f"rejected {item_id}" + (f": {reason}" if reason else ""))

    def comment(self, task_id, text):
        self.client.comment(self.rush.ACTOR, task_id, f"{text.strip()}\n\n{PJ_SIGNOFF}")
        self.store.journal(f"PJ commented on {task_id} from the remote")

    def reply(self, message_id, text):
        msg = self.client.message(message_id)
        sender = (msg.get("attributedTo") or "").rstrip("/").rsplit("/", 1)[-1]
        self.client.send(
            self.rush.ACTOR,
            [sender],
            f"{text.strip()}\n\n{PJ_SIGNOFF}",
            summary=msg.get("summary") and f"re: {msg['summary']}",
            in_reply_to=msg.get("id"),
        )
        self.store.journal(f"PJ replied to {message_id} from the remote")

    def start_tick(self):
        """Run one heartbeat in the background; False if one is already running."""
        if self.tick is None or not self.ticking.acquire(blocking=False):
            return False

        def run():
            try:
                self.tick()
            finally:
                self.ticking.release()

        threading.Thread(target=run, daemon=True).start()
        return True

    # --- pages
    def form(self, action, inner, button, cls="go"):
        return (
            f'<form method="post" action="{action}">'
            f'<input type="hidden" name="token" value="{self.token}">{inner}'
            f'<div class="row"><button class="{cls}">{button}</button></div></form>'
        )

    def usage_page(self):
        """Claude Code's usage over the whole history (light_labs.core.usage)."""
        from light_labs.core import usage

        try:
            body = usage.render(usage.report(self.usage_db))
        except usage.Unavailable as e:
            body = f'<p class="meta">{esc(str(e))}</p>'
        return page("Rush · usage", "<h2>Claude Code usage</h2>" + body)

    def queue_page(self):
        items = self.store.pending()
        cards = []
        for i in items:
            tags = " ".join(
                f'<span class="tag">{esc(t)}</span>'
                for t in (["escalate: " + i["escalate"]] if i.get("escalate") else [])
                + i.get("held", [])
            )
            where = i["target"].get("task_id") or ", ".join(i["target"].get("to", []))
            approve = self.form(
                f"/approve/{i['id']}",
                f'<textarea name="text">{esc(i["draft"])}</textarea>',
                "Send",
            )
            reject = self.form(
                f"/reject/{i['id']}",
                '<input type="text" name="reason" placeholder="why (optional)">',
                "Reject",
                cls="",
            )
            cards.append(
                f'<div class="card" id="{esc(i["id"])}"><div class="meta">{esc(i["id"])} · {esc(i["kind"])} → '
                f"{esc(where)} · {esc(i['created'][:16])}</div>{tags}"
                f'<div class="ctx">{esc(i["context"], CLIP)}</div>{approve}{reject}</div>'
            )
        journal = self.store.root / "journal.md"
        lines = journal.read_text().splitlines()[-JOURNAL_LINES:] if journal.exists() else []
        busy = self.ticking.locked()
        tick = self.form("/tick", "", "Ticking…" if busy else "Check the board now", cls="")
        body = (
            f"<h2>Waiting for you ({len(items)})</h2>"
            + ("".join(cards) or '<p class="meta">Nothing pending.</p>')
            + f"<h2>Heartbeat</h2>{tick}"
            + f"<h2>Journal</h2><pre>{esc(chr(10).join(reversed(lines)))}</pre>"
        )
        return page("Rush · queue", body)

    def board_page(self):
        tasks = board_view(self.client.list_tasks(), self.rush.ACTOR)
        cards = []
        for t in tasks:
            last = (t.get("comments") or [{}])[-1]
            cards.append(
                f'<div class="card"><a href="/task/{esc(t["id"])}"><b>{esc(t["title"])}</b></a>'
                f'<div class="meta">{esc(t.get("column"))} · {esc((t.get("updatedAt") or "")[:16])}'
                f" · {len(t.get('comments') or [])} comments</div>"
                + (
                    f'<div class="ctx">{esc(last.get("author"))}: {esc(last.get("text"), 280)}</div>'
                    if last
                    else ""
                )
                + "</div>"
            )
        return page("Rush · board", "<h2>Naming PJ or Rush</h2>" + "".join(cards))

    def task_page(self, task_id):
        t = self.client.task(task_id)
        comments = (t.get("comments") or [])[-10:]
        thread = "".join(
            f'<div class="card"><div class="meta">{esc(c.get("author"))} · '
            f'{esc((c.get("at") or "")[:16])}</div><div class="ctx">{esc(c.get("text"), 2000)}'
            "</div></div>"
            for c in comments
        )
        body = (
            f"<h2>{esc(t.get('column'))} · {esc(task_id)}</h2><h3>{esc(t.get('title'))}</h3>"
            f'<div class="card"><div class="ctx">{esc(t.get("description"), 3000)}</div></div>'
            f"<h2>Latest comments</h2>{thread}<h2>Comment as PJ</h2>"
            + self.form(f"/comment/{esc(task_id)}", '<textarea name="text"></textarea>', "Post")
        )
        return page(t.get("title") or task_id, body)

    def mail_page(self):
        """Triaged mail across accounts, needs_reply first, each linked to Gmail. Only
        what triage kept (sender, subject, summary); message contents stay in Gmail."""
        from light_labs.agents.rush.mail import LABELS, Inbox, gmail_link

        items = []
        for account in getattr(self.rush, "MAIL_ACCOUNTS", []):
            items += Inbox(self.store, account, None).recent()
        items.sort(key=lambda i: i.get("date", ""), reverse=True)
        body = ""
        for label in LABELS:
            group = [i for i in items if i.get("label") == label]
            if not group:
                continue
            body += f"<h2>{esc(label.replace('_', ' '))} ({len(group)})</h2>" + "".join(
                f'<div class="card"><a href="{esc(gmail_link(i))}"><b>{esc(i["subject"] or "(no subject)")}</b></a>'
                f'<div class="meta">{esc(i["from"], 80)} · {esc(i["account"])} · {esc(i.get("by"))}</div>'
                f'<div class="ctx">{esc(i.get("summary"))}</div></div>'
                for i in group[:30]
            )
        return page("Rush · mail", body or '<p class="meta">No mail triaged yet.</p>')

    def inbox_page(self):
        items = self.client.inbox(self.rush.ACTOR).get("items", [])[-15:]
        cards = "".join(
            f'<div class="card"><a href="/msg/{esc(i["id"].rstrip("/").rsplit("/", 1)[-1])}">'
            f"<b>{esc(i.get('summary') or '(no subject)')}</b></a>"
            f'<div class="meta">{esc(i["attributedTo"].rstrip("/").rsplit("/", 1)[-1])} · '
            f"{esc((i.get('published') or '')[:16])}{' · broadcast' if i.get('broadcast') else ''}"
            "</div></div>"
            for i in reversed(items)
        )
        return page("Rush · inbox", "<h2>pj_agent inbox</h2>" + cards)

    def msg_page(self, message_id):
        m = self.client.message(message_id)
        body = (
            f"<h2>{esc(m.get('summary') or '(no subject)')}</h2>"
            f'<div class="card"><div class="ctx">{esc(m.get("content"), 6000)}</div></div>'
            "<h2>Reply as PJ</h2>"
            + self.form(f"/reply/{esc(message_id)}", '<textarea name="text"></textarea>', "Send")
        )
        return page("Rush · message", body)


def handler(remote):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # one line per request on stdout
            print(f"{now()} {self.command} {self.path} {args[1] if len(args) > 1 else ''}")

        def _allowed(self):
            login = self.headers.get("Tailscale-User-Login", "")
            if login in remote.allowed:
                return True
            self._send(403, page("Not allowed", "<p>Tailnet login required.</p>"))
            return False

        def _send(self, code, body, location=None):
            data = body.encode()
            self.send_response(code)
            if location:
                self.send_header("Location", location)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self._allowed():
                return
            parts = urlparse(self.path).path.strip("/").split("/")
            flash = parse_qs(urlparse(self.path).query).get("done", [None])[0]
            try:
                if parts == [""]:
                    body = remote.queue_page()
                elif parts == ["board"]:
                    body = remote.board_page()
                elif parts == ["mail"]:
                    body = remote.mail_page()
                elif parts == ["inbox"]:
                    body = remote.inbox_page()
                elif parts == ["usage"]:
                    body = remote.usage_page()
                elif len(parts) == 2 and parts[0] == "task":
                    body = remote.task_page(parts[1])
                elif len(parts) == 2 and parts[0] == "msg":
                    body = remote.msg_page(parts[1])
                else:
                    return self._send(404, page("Not found", "<p>Not found.</p>"))
            except OSError as e:  # the edge is down or slow
                return self._send(502, page("Edge unreachable", f"<p>{esc(str(e))}</p>"))
            if flash:
                body = body.replace("<main>", f'<main><div class="flash">{esc(flash)}</div>', 1)
            self._send(200, body)

        def do_POST(self):
            if not self._allowed():
                return
            length = int(self.headers.get("Content-Length") or 0)
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
            if not secrets.compare_digest(form.get("token", ""), remote.token):
                return self._send(403, page("Stale page", "<p>Reload and try again.</p>"))
            parts = urlparse(self.path).path.strip("/").split("/")
            text = form.get("text", "")
            try:
                if parts == ["tick"]:
                    started = remote.start_tick()
                    done, back = ("Checking the board" if started else "Already checking"), "/"
                elif len(parts) == 2 and parts[0] == "approve":
                    remote.approve(parts[1], text)
                    done, back = f"Sent {parts[1]}", "/"
                elif len(parts) == 2 and parts[0] == "reject":
                    remote.reject(parts[1], form.get("reason", ""))
                    done, back = f"Rejected {parts[1]}", "/"
                elif len(parts) == 2 and parts[0] == "comment" and text.strip():
                    remote.comment(parts[1], text)
                    done, back = "Posted", f"/task/{parts[1]}"
                elif len(parts) == 2 and parts[0] == "reply" and text.strip():
                    remote.reply(parts[1], text)
                    done, back = "Sent", "/inbox"
                else:
                    return self._send(400, page("Bad request", "<p>Nothing to do.</p>"))
            except FileNotFoundError:
                return self._send(404, page("Gone", "<p>Already handled.</p>"))
            except OSError as e:
                return self._send(502, page("Edge unreachable", f"<p>{esc(str(e))}</p>"))
            self._send(303, "", location=f"{back}?done={done.replace(' ', '+')}")

    return Handler


def serve(store, rush, host="127.0.0.1", port=8787, allowed=None, tick=None):
    remote = Remote(store, rush, allowed=allowed or [tailnet_login()], tick=tick)
    server = ThreadingHTTPServer((host, port), handler(remote))
    if rush.TELEGRAM_CHAT:  # PJ's replies on Telegram, handled while the Mac is awake
        from light_labs.agents.rush.telegram import Telegram

        try:
            tg = Telegram.from_keychain(rush.TELEGRAM_CHAT, store.root / "telegram.json")
        except subprocess.CalledProcessError:
            print("Telegram: no token in Keychain; page only")
        else:
            threading.Thread(target=tg.poll_forever, args=(remote,), daemon=True).start()
            print("Telegram: polling")
    from light_labs.agents import roll

    if roll.TELEGRAM_CHAT:  # Roll's rule approvals, read by the same always-on process
        try:
            rbot = roll.bot()
        except subprocess.CalledProcessError:
            print("Roll: no token in Keychain")
        else:
            threading.Thread(target=rbot.poll_forever, args=(None,), daemon=True).start()
            print("Roll: polling")
    print(f"Rush remote on http://{host}:{port} for {sorted(remote.allowed)}")
    server.serve_forever()


def cli_tick(store, rush):
    """The same heartbeat `lab rush tick` runs."""
    from light_labs import cli

    return lambda: cli.rush_tick(Namespace(backfill=False), store, rush)
