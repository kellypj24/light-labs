"""Who is asking, for the pages `tailscale serve` publishes (Rush's remote, Workouts).

Each page listens on 127.0.0.1; `tailscale serve` forwards tailnet requests to it and names
the caller in the Tailscale-User-Login header. A page answers only an allowed login, and
only a Host that is this machine's tailnet name or loopback: without the Host check, a web
page open in PJ's browser could rebind its own name to 127.0.0.1 and send the login header
itself.
"""

import json
import subprocess

LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


def tailnet_login():
    """This machine's Tailscale login, the default allowed user."""
    out = subprocess.run(
        ["tailscale", "status", "--json"], capture_output=True, text=True, check=True
    ).stdout
    d = json.loads(out)
    return d["User"][str(d["Self"]["UserID"])]["LoginName"]


def tailnet_hosts():
    """This machine's MagicDNS names, full and short: the Hosts `tailscale serve` forwards.
    Empty when Tailscale is down or has no name; the page then answers loopback only."""
    try:
        out = subprocess.run(
            ["tailscale", "status", "--json"], capture_output=True, text=True, check=True
        ).stdout
        full = (json.loads(out).get("Self") or {}).get("DNSName") or ""
    except (OSError, subprocess.CalledProcessError, ValueError):
        return set()
    full = full.rstrip(".").lower()
    return {full, full.split(".")[0]} if full else set()


def request_host(value):
    """The Host header without its port or a trailing dot, lowercased; "" if absent."""
    value = (value or "").strip().lower()
    if value.startswith("["):  # [::1] or [::1]:8787
        return value[1 : value.find("]")] if "]" in value else ""
    head, sep, port = value.rpartition(":")
    if sep and head and port.isdigit():
        value = head
    return value.rstrip(".")


def refusal(headers, hosts, logins):
    """Why a request is refused ("Unknown host.", "Tailnet login required."), or None."""
    host = request_host(headers.get("Host"))
    if not host or host not in hosts:
        return "Unknown host."
    if headers.get("Tailscale-User-Login", "") not in logins:
        return "Tailnet login required."
    return None
