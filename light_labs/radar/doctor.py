"""`lab radar doctor`: permissions, helper state, data freshness. Each check says how to fix it."""

from __future__ import annotations

import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import duckdb

from light_labs.radar import helper
from light_labs.radar.config import Paths, Settings

FDA_STEPS = """\
Grant Full Disk Access to the helper binary only (not your terminal, not Python):
  1. System Settings > Privacy & Security > Full Disk Access
  2. Click +, press Cmd-Shift-G, paste: {binary}
  3. Open, then make sure its toggle is on
  4. lab radar sync
A rebuild (`lab radar helper build`) changes the binary's hash: remove and re-add it."""


@dataclass(frozen=True)
class Check:
    name: str
    level: str  # ok | warn | fail
    detail: str
    fix: str | None = None


def _age_days(p: Path) -> float:
    return (time.time() - p.stat().st_mtime) / 86400


def run(paths: Paths, settings: Settings) -> list[Check]:
    out: list[Check] = []
    if not paths.home.exists():
        return [Check("home", "fail", f"{paths.home} missing", "lab radar init")]
    mode = stat.S_IMODE(paths.home.stat().st_mode)
    out.append(
        Check("home", "ok", f"{paths.home} (0{mode:o})")
        if mode & 0o077 == 0
        else Check("home", "fail", f"{paths.home} is 0{mode:o}", f"chmod 700 {paths.home}")
    )
    for f in (paths.config, paths.circles, paths.overrides):
        if not f.exists():
            out.append(Check(f.name, "warn", "missing", "lab radar init (copies the examples)"))

    binary = helper.binary_path(paths)
    if not binary.exists():
        out.append(Check("helper", "fail", "not built", "lab radar helper build"))
    else:
        sig = subprocess.run(
            ["codesign", "-dv", str(binary)], check=False, capture_output=True, text=True
        )
        runtime = "runtime" in sig.stderr
        out.append(
            Check("helper", "ok", f"{binary} (hardened runtime)")
            if runtime
            else Check(
                "helper", "fail", "not signed with the hardened runtime", "lab radar helper build"
            )
        )
        out.append(
            Check("helper agent", "ok", f"{helper.LABEL} loaded")
            if helper.is_loaded()
            else Check(
                "helper agent", "warn", "LaunchAgent not installed", "lab radar helper install"
            )
        )
    last = helper.last_log_line(paths)
    if last and ("Full Disk Access" in last or "authoriz" in last):
        out.append(Check("full disk access", "fail", last, FDA_STEPS.format(binary=binary)))

    exp = paths.messages_export
    if not exp.exists():
        out.append(
            Check("messages export", "warn", "no export yet", FDA_STEPS.format(binary=binary))
        )
    else:
        age = _age_days(exp)
        level = "ok" if age < 2 else "warn"
        out.append(
            Check(
                "messages export",
                level,
                f"{age:.1f} days old",
                None if level == "ok" else "lab radar sync; check logs/messages-export.log",
            )
        )

    vcfs = sorted(paths.contacts_dir.glob("*.vcf"))
    if not vcfs:
        out.append(
            Check(
                "contacts",
                "warn",
                f"no .vcf in {paths.contacts_dir}",
                "Contacts.app: select all, File > Export > Export vCard, save there",
            )
        )
    else:
        age = min(_age_days(v) for v in vcfs)
        out.append(
            Check(
                "contacts",
                "ok" if age < 45 else "warn",
                f"newest export {age:.0f} days old",
                None if age < 45 else "export Contacts again",
            )
        )

    if paths.db.exists():
        con = duckdb.connect(str(paths.db), read_only=True)
        try:
            for source, status, finished, msg in con.execute(
                """
                SELECT source, arg_max(status, started_at), max(finished_at),
                       arg_max(message, started_at)
                FROM runs GROUP BY source ORDER BY source
                """
            ).fetchall():
                level = {"ok": "ok", "skipped": "warn"}.get(status, "fail")
                out.append(
                    Check(
                        f"source {source}",
                        level,
                        f"last run {status} at {finished:%Y-%m-%d %H:%M}"
                        + (f": {msg}" if msg else ""),
                    )
                )
            channels = dict(
                con.execute(
                    "SELECT channel, count(*) FROM interactions "
                    "WHERE source = 'imessage' GROUP BY ALL"
                ).fetchall()
            )
            if channels and not (channels.get("sms") or channels.get("rcs")):
                out.append(
                    Check(
                        "sms/rcs",
                        "warn",
                        "only iMessage rows: texts with non-Apple phones are missing",
                        "iPhone: Settings > Apps > Messages > Text Message Forwarding > this Mac; "
                        "and Messages in iCloud for history",
                    )
                )
        finally:
            con.close()
    else:
        out.append(Check("database", "warn", "no database yet", "lab radar sync"))

    if paths.review_matches.exists():
        pending = sum(
            1
            for line in paths.review_matches.read_text().splitlines()[1:]
            if line.rstrip().endswith(",")
        )
        if pending:
            out.append(
                Check(
                    "review",
                    "warn",
                    f"{pending} possible matches to review",
                    f"set decision to merge or different in {paths.review_matches}",
                )
            )

    if settings.output_dir is None:
        out.append(
            Check(
                "output",
                "warn",
                "Google Drive for Desktop not found; local copies only",
                "install Drive for Desktop, or set output_dir in config.yaml",
            )
        )
    else:
        exists = settings.output_dir.parent.exists()
        out.append(
            Check(
                "output",
                "ok" if exists else "warn",
                str(settings.output_dir),
                None if exists else "is Google Drive for Desktop signed in?",
            )
        )
    return out
