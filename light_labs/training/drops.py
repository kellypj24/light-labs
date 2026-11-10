"""Landing a training export in its inbox, whichever way it arrived.

Rush calls `land` for a file or JSON text on Telegram, and the remote page for a POST
to /drop/<kind> from the phone's Shortcut over the tailnet. The data is checked by the
source's own parser first, so a wrong file is refused before Dagster sees it.

- strong: var/training/strong/inbox/strong-<yyyy-mm-dd>.csv. A second drop the same day
  replaces the first; each export is the whole history.
- health: var/training/health/inbox/health-<yyyy-mm-dd-hhmmss>.json. Every drop is kept;
  each covers a window.
"""

import csv
from datetime import datetime
from pathlib import Path

from light_labs import config

KINDS = ("strong", "health")
MAX_BYTES = 20 * 1024 * 1024


class Refused(ValueError):
    """Not an export this lab knows; the message says why, for the sender."""


def sniff(data):
    """'health' for JSON, else 'strong'."""
    return "health" if data.lstrip(b"\xef\xbb\xbf \t\r\n")[:1] in (b"{", b"[") else "strong"


def _write(out, data):
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(out)  # the sensor never sees half a file


def land(kind, data, at=None, root=None):
    """Check `data` and save it to <root>/<kind>/inbox/. Returns the reply text."""
    root = Path(root or config.VAR / "training")
    at = at or datetime.now()
    if kind not in KINDS:
        raise Refused(f"unknown kind {kind!r}; one of {', '.join(KINDS)}")
    if len(data) > MAX_BYTES:
        raise Refused("over 20 MB")
    if kind == "health":
        from light_labs.training import health

        try:
            _, workouts = health.parse(data)
        except (health.NotHealth, UnicodeDecodeError) as e:
            raise Refused(f"Not a Health workouts export: {e}") from None
        out = root / "health" / "inbox" / f"health-{at:%Y-%m-%d-%H%M%S}.json"
        _write(out, data)
        return f"Got {health.summary(workouts)}. Saved {out.name}."
    from light_labs.training import strong

    try:
        sets = strong.parse(data)
    except (strong.NotStrong, UnicodeDecodeError, csv.Error) as e:
        raise Refused(f"Not a Strong export: {e}") from None
    out = root / "strong" / "inbox" / f"strong-{at:%Y-%m-%d}.csv"
    _write(out, data)
    return f"Got {strong.summary(sets)}. Saved {out.name}."
