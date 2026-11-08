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
  4. lab radar helper install   (once; it runs the helper as its own process)
  5. lab radar sync
A rebuild (`lab radar helper build`) changes the binary's hash: remove and re-add it."""


@dataclass(frozen=True)
class Check:
    name: str
    level: str  # ok | warn | fail
    detail: str
    fix: str | None = None


def _age_days(p: Path) -> float:
    return (time.time() - p.stat().st_mtime) / 86400


def helper_checks(paths: Paths) -> list[Check]:
    """Approval state of the helper source, the binary's signature and the LaunchAgent."""
    out: list[Check] = []
    st = helper.source_state(paths)
    if st["approved"] is None:
        out.append(Check("helper source", "fail", "never approved", "lab radar helper approve"))
    elif st["repo"] != st["approved"]:
        out.append(Check(
            "helper source", "warn",
            "the repo's helper changed since you approved it (the binary still uses yours)",
            "lab radar helper approve  # read the diff before typing approve",
        ))  # fmt: skip
    else:
        out.append(Check("helper source", "ok", f"approved {st['approved'][:12]}"))
    binary = helper.binary_path(paths)
    if not binary.exists():
        out.append(Check("helper", "fail", "not built", "lab radar helper build"))
        return out
    if st["built"] != st["approved"]:
        out.append(Check("helper", "warn", "built from an older approval",
                         "lab radar helper build, then re-grant Full Disk Access"))  # fmt: skip
    sig = subprocess.run(
        [helper.CODESIGN, "-dv", str(binary)], check=False, capture_output=True, text=True
    )
    if "runtime" in sig.stderr:
        out.append(Check("helper", "ok", f"{binary} (hardened runtime)"))
    else:
        out.append(Check("helper", "fail", "not signed with the hardened runtime",
                         "lab radar helper build"))  # fmt: skip
    from light_labs.radar import schedule

    for job in schedule.JOBS:
        if not schedule.loaded(job):
            out.append(Check(f"schedule {job}", "warn", "LaunchAgent not installed",
                             "lab radar schedule install"))  # fmt: skip
    if helper.is_loaded():
        out.append(Check("helper agent", "ok", f"{helper.LABEL} loaded"))
    else:
        out.append(Check("helper agent", "warn", "LaunchAgent not installed",
                         "lab radar helper install"))  # fmt: skip
    return out


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

    out += helper_checks(paths)
    binary = helper.binary_path(paths)
    last = helper.last_log_line(paths)
    if last and ("Full Disk Access" in last or "authoriz" in last):
        out.append(Check("full disk access", "fail", last, FDA_STEPS.format(binary=binary)))
    exp = paths.messages_export
    if exp.exists() and _age_days(exp) > 1:
        # Ingest deletes the export, so one that lingers was never read.
        out.append(Check("messages export", "warn", f"waiting {_age_days(exp):.1f} days",
                         "lab radar sync"))  # fmt: skip

    vcfs = sorted(paths.contacts_dir.glob("*.vcf"))
    if vcfs and min(_age_days(v) for v in vcfs) > 90:
        # vCards are optional (the helper exports Contacts); an old one may be stale.
        out.append(Check("vcards", "warn", "newest vCard export is over 90 days old",
                         f"export again into {paths.contacts_dir}, or delete it"))  # fmt: skip

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
