"""`lab radar page`: the weekly digest as a read-only page on the tailnet.

The picks reach PJ's phone as a page on his own machines, not as a message a third party
stores. Rush texts the link (radar/notice.py) and never reads what is behind it.

Access is Workouts' (`core/tailnet.py`): 127.0.0.1 behind `tailscale serve`, an allowed
tailnet login, this machine's Host. The process opens no database and reads one file, the
copy `lab radar weekly` writes for it, which never carries snippets. GET `/` is the only
route; there is no form and nothing to write. Stdlib only.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from light_labs.core.tailnet import LOOPBACK, refusal, tailnet_hosts, tailnet_login

NAME = "Radar"
PORT = 8789
CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
EMPTY = "<p>No digest yet. <code>lab radar weekly</code> writes one.</p>"

CSS = """
:root { color-scheme: light dark; --fg: #1c1c1e; --dim: #6b6b70; --bg: #fff; --line: #e3e3e6; }
@media (prefers-color-scheme: dark) {
  :root { --fg: #f2f2f7; --dim: #9a9aa0; --bg: #111113; --line: #2c2c30; }
}
body { margin: 0 auto; padding: 16px; max-width: 40rem; background: var(--bg); color: var(--fg);
  font: 16px/1.45 -apple-system, system-ui, sans-serif; }
h1 { font-size: 1.25rem; margin: 0 0 .5rem; }
h2 { font-size: 1rem; margin: 1.5rem 0 .5rem; padding-top: .75rem; border-top: 1px solid var(--line); }
p, .sub, footer { color: var(--dim); font-size: .875rem; }
ol, ul { padding-left: 1.25rem; margin: 0; }
li { margin: 0 0 .75rem; }
.sub { margin-top: .125rem; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: .25rem .5rem .25rem 0; border-bottom: 1px solid var(--line); }
th.n, td.n { text-align: right; padding-right: 0; }
code { font: .875em ui-monospace, monospace; }
footer { margin-top: 2rem; }
"""

_ITEM = re.compile(r"(\d+\.|-) (.*)")
_CELLS = re.compile(r"(?<!\\)\|")


def inline(text: str) -> str:
    """One line of the digest's Markdown as HTML. `digest.safe` backslash-escapes every
    Markdown character in a name, so an escaped character is literal text here, and all
    text is HTML-escaped: a name can become neither markup nor a link."""
    out, i, open_ = [], 0, {"**": False, "`": False}
    tags = {"**": "strong", "`": "code"}
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            out.append(html.escape(text[i + 1]))
            i += 2
            continue
        mark = "**" if text.startswith("**", i) else "`" if text[i] == "`" else None
        if mark:
            out.append(f"<{'/' if open_[mark] else ''}{tags[mark]}>")
            open_[mark] = not open_[mark]
            i += len(mark)
            continue
        out.append(html.escape(text[i]))
        i += 1
    out += [f"</{tags[m]}>" for m in ("`", "**") if open_[m]]  # an unclosed mark ends here
    return "".join(out)


def _table(rows: list[str]) -> str:
    cells = [[c.strip() for c in _CELLS.split(r.strip().strip("|"))] for r in rows]
    right = [":" in c for c in cells[1]] if len(cells) > 1 else []

    def row(tag, values):
        return "".join(
            f"<{tag}{' class=n' if i < len(right) and right[i] else ''}>{inline(v)}</{tag}>"
            for i, v in enumerate(values)
        )

    body = "".join(f"<tr>{row('td', r)}</tr>" for r in cells[2:])
    return f"<table><tr>{row('th', cells[0])}</tr>{body}</table>"


def render(markdown: str) -> str:
    """The digest's own Markdown (digest.render) as HTML: headings, the two list kinds
    with their indented lines, the stats table, paragraphs. Nothing else is recognized."""
    out: list[str] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.startswith("## "):
            out.append(f"<h2>{inline(line[3:])}</h2>")
            i += 1
        elif line.startswith("# "):
            out.append(f"<h1>{inline(line[2:])}</h1>")
            i += 1
        elif line.startswith("|"):
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            out.append(_table(lines[i:j]))
            i = j
        elif m := _ITEM.fullmatch(line):
            tag = "ul" if m[1] == "-" else "ol"
            out.append(f"<{tag}>")
            while (
                i < len(lines)
                and (m := _ITEM.fullmatch(lines[i]))
                and (m[1] == "-") == (tag == "ul")
            ):
                item = [inline(m[2])]
                i += 1
                while i < len(lines) and lines[i].startswith("  ") and lines[i].strip():
                    item.append(f'<div class="sub">{inline(lines[i].strip())}</div>')
                    i += 1
                out.append(f"<li>{''.join(item)}</li>")
            out.append(f"</{tag}>")
        else:
            out.append(f"<p>{inline(line.strip())}</p>")
            i += 1
    return "\n".join(out)


def shell(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        '<meta name="robots" content="noindex">'
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body>{body}</body></html>"
    )


class Page:
    def __init__(self, digest: Path, allowed=(), hosts=()):
        self.digest = digest
        self.allowed = set(allowed)
        self.hosts = LOOPBACK | {h.lower() for h in hosts if h}

    def html(self) -> str:
        try:
            text = self.digest.read_text()
            written = datetime.fromtimestamp(self.digest.stat().st_mtime)
        except OSError:
            return shell(NAME, EMPTY)
        foot = f"<footer>Written {written:%a %b} {written.day}, {written:%H:%M}.</footer>"
        return shell(NAME, render(text) + foot)


def handler(page: Page):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # method, path and status: never a name
            status = args[1] if len(args) > 1 else ""
            print(
                f"{datetime.now():%Y-%m-%d %H:%M:%S} {self.command} {self.path} {status}",
                flush=True,
            )

        def _send(self, code, body):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            why = refusal(self.headers, page.hosts, page.allowed)
            if why:
                return self._send(403, shell("Not allowed", f"<p>{why}</p>"))
            if urlparse(self.path).path != "/":
                return self._send(404, shell("Not found", "<p>Not found.</p>"))
            self._send(200, page.html())

    return Handler


def serve(digest: Path, host="127.0.0.1", port=PORT, allowed=None):
    page = Page(digest, allowed=allowed or [tailnet_login()], hosts=tailnet_hosts())
    server = ThreadingHTTPServer((host, port), handler(page))
    print(f"{NAME} on http://{host}:{port} for {sorted(page.allowed)}", flush=True)
    server.serve_forever()
