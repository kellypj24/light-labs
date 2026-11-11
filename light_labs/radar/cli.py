"""`lab radar`: sync, bootstrap, weekly, person, doctor, purge, helper, schedule.

Parsers only at import time; the handlers import Radar's modules, which need the `radar`
dependency group (`uv run --group radar lab radar ...`).
"""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent / "examples"
log = logging.getLogger("radar")


def register(sub) -> None:
    p = sub.add_parser("radar", help="Relationship Radar: who to reach out to (docs/radar.md)")
    cmd = p.add_subparsers(dest="cmd", required=True)
    cmd.add_parser("init", help="create ~/.relationship-radar and copy the example config")
    s = cmd.add_parser("sync", help="pull new data from every source, then re-resolve people")
    s.add_argument("--source", help="only this source")
    s.add_argument("--with-snippets", action="store_true", help="keep the last preview per contact")
    s.add_argument("--no-kick", action="store_true", help="don't run the Messages helper first")
    b = cmd.add_parser("bootstrap", help="propose circles into circles.proposed.yaml")
    b.add_argument("--as-of", help="YYYY-MM-DD (default: now)")
    w = cmd.add_parser("weekly", help="write the weekly digest (shared and dated local copy)")
    w.add_argument("--with-snippets", action="store_true", help="snippets in the local copy only")
    w.add_argument("--as-of", help="YYYY-MM-DD (default: now)")
    pe = cmd.add_parser("person", help="one person's identities, metrics and timeline")
    pe.add_argument("name")
    pe.add_argument("--limit", type=int, default=30)
    cmd.add_parser("doctor", help="permissions, the helper and data freshness, with fixes")
    pu = cmd.add_parser("purge", help="delete everything Radar stored, incl. the shared digest")
    pu.add_argument("--all", dest="all_", action="store_true", help="also config and overrides")
    pu.add_argument("--yes", action="store_true")
    h = cmd.add_parser("helper", help="the Messages export helper (the only code with FDA)")
    hcmd = h.add_subparsers(dest="helper_cmd", required=True)
    hcmd.add_parser("approve", help="read the helper source's diff and approve it (terminal only)")
    hb = hcmd.add_parser("build", help="compile the approved copy; re-grant FDA after a build")
    hb.add_argument("--snippets", action="store_true", help="compile in 140-char previews")
    hcmd.add_parser("install", help="LaunchAgent: daily 06:20 and on `lab radar sync`")
    hcmd.add_parser("uninstall", help="remove the LaunchAgent and binary")
    sc = cmd.add_parser(
        "schedule", help="LaunchAgents on the release: sync 06:30, weekly Fri 15:00"
    )
    sc.add_argument("action", choices=["install", "uninstall"])


def run(args) -> int:
    handler = {
        "init": init,
        "sync": sync,
        "bootstrap": bootstrap,
        "weekly": weekly,
        "person": person,
        "doctor": doctor_cmd,
        "purge": purge,
        "helper": helper_cmd,
        "schedule": schedule_cmd,
    }[args.cmd]
    return handler(args) or 0


def _setup():
    from light_labs.radar.config import Paths, Settings, radar_home

    paths = Paths(radar_home())
    paths.ensure()
    # Radar's own logger only: the rest of `lab` keeps its logging untouched.
    for h in list(log.handlers):
        log.removeHandler(h)
        h.close()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(), logging.FileHandler(paths.logs / "radar.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)
    log.propagate = False
    return paths, Settings.load(paths)


def _as_of(value: str | None) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC) if value else datetime.now(UTC)


def init(args) -> None:
    paths, _ = _setup()
    for name, dest in (
        ("config", paths.config),
        ("circles", paths.circles),
        ("overrides", paths.overrides),
    ):
        if not dest.exists():
            shutil.copy(EXAMPLES / f"{name}.example.yaml", dest)
            dest.chmod(0o600)
            print(f"wrote {dest}")
    print(f"ready: {paths.home}")


def sync(args) -> int:
    from light_labs.radar import helper, resolve
    from light_labs.radar.db import connect
    from light_labs.radar.sources import registry
    from light_labs.radar.sources.base import SyncContext, run_source

    paths, settings = _setup()
    sources = registry()
    if args.source and args.source not in sources:
        print(f"unknown source {args.source}; one of {', '.join(sources)}")
        return 2
    if not args.no_kick and args.source in (None, "imessage") and not helper.kick(paths):
        log.warning("imessage: helper not run (not installed or timed out); using last export")
    ctx = SyncContext(paths, settings, args.with_snippets)
    con = connect(paths.db)
    for name, s in sources.items():
        if args.source and name != args.source:
            continue
        r = run_source(con, s, ctx)
        print(f"{name}: {r.status}, {r.rows_in} new" + (f" ({r.message})" if r.message else ""))
    con.begin()
    res = resolve.resolve(con, paths, settings)
    con.commit()
    con.close()
    paths.db.chmod(0o600)
    print(f"people: {res.people}; auto-merged {res.auto_merged}; to review {res.review_rows}")
    return 0


def bootstrap(args) -> None:
    from light_labs.radar import circles, metrics
    from light_labs.radar.db import connect

    paths, settings = _setup()
    con = connect(paths.db)
    when = _as_of(args.as_of)
    counts = circles.write_proposal(
        paths.circles_proposed, metrics.compute(con, when, settings.two_way_window_days), when
    )
    print(", ".join(f"{c}: {n}" for c, n in counts.items()))
    if circles.apply_if_empty(paths.circles_proposed, paths.circles):
        print(f"applied to {paths.circles} (it had no people); edit it to correct any circle")
    else:
        print(f"review {paths.circles_proposed}; copy what you agree with into {paths.circles}")


def weekly(args) -> None:
    from light_labs.radar import circles, digest, metrics
    from light_labs.radar.db import connect

    paths, settings = _setup()
    con = connect(paths.db)
    when = _as_of(args.as_of)
    assigned = circles.load(con, paths.circles, settings.default_region)
    m = metrics.compute(con, when, settings.two_way_window_days)
    shared = digest.render(con, m, assigned, settings.former_employers, when)
    local = shared
    if args.with_snippets:
        snippets = digest.latest_snippets(con)
        local = digest.render(con, m, assigned, settings.former_employers, when, snippets)
    dated = paths.digests / f"{when.date().isoformat()}.md"
    dated.write_text(local)
    dated.chmod(0o600)
    print(f"wrote {dated}")
    if settings.output_dir:
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        out = settings.output_dir / "weekly-digest.md"
        out.write_text(shared)
        print(f"wrote {out}")
    else:
        log.warning("no output_dir (Google Drive for Desktop not found): local copy only")


def person(args) -> int:
    from light_labs.radar import metrics
    from light_labs.radar.db import connect

    paths, _ = _setup()
    con = connect(paths.db)
    rows = con.execute(
        "SELECT person_id, display_name FROM people WHERE display_name ILIKE ? ORDER BY 2",
        [f"%{args.name}%"],
    ).fetchall()
    if not rows:
        print(f"no one matches {args.name!r}")
        return 1
    if len(rows) > 1:
        print("several match: " + "; ".join(f"{n} ({p})" for p, n in rows[:10]))
    pid, display = rows[0]
    m = next((x for x in metrics.compute(con, datetime.now(UTC)) if x.person_id == pid), None)
    print(f"{display} ({pid})")
    for kind, value, method in con.execute(
        "SELECT kind, value_norm, match_method FROM identities WHERE person_id = ? ORDER BY 1, 2",
        [pid],
    ).fetchall():
        print(f"  {kind}: {value} [{method}]")
    if m and m.last_contact:
        print(f"  last contact {m.last_contact:%Y-%m-%d} via {m.last_channel}")
        print(
            f"  last two-way {m.last_two_way}; 90d: {m.n_90d} ({m.trend}); "
            f"active {m.active_in(0, 11)}/12 months"
        )
    elif m:
        print("  no contact on record")
    for ts, channel, direction, is_group in con.execute(
        """
        SELECT ts, channel, direction, is_group FROM person_interactions
        WHERE person_id = ? ORDER BY ts DESC LIMIT ?
        """,
        [pid, args.limit],
    ).fetchall():
        print(f"  {ts:%Y-%m-%d %H:%M}  {channel:<8} {direction:<8} {'group' if is_group else ''}")
    return 0


def doctor_cmd(args) -> int:
    from light_labs.radar import doctor

    paths, settings = _setup()
    checks = doctor.run(paths, settings)
    mark = {"ok": "ok  ", "warn": "WARN", "fail": "FAIL"}
    for c in checks:
        print(f"{mark[c.level]} {c.name}: {c.detail}")
        if c.fix and c.level != "ok":
            print("     " + c.fix.replace("\n", "\n     "))
    return 1 if any(c.level == "fail" for c in checks) else 0


def purge(args) -> int:
    paths, settings = _setup()
    targets = [
        paths.db,
        paths.db.with_suffix(".duckdb.wal"),
        paths.inbox,
        paths.digests,
        paths.logs,
        paths.review_matches,
        paths.circles_proposed,
    ]
    if settings.output_dir:
        targets.append(settings.output_dir / "weekly-digest.md")
    if args.all_:
        targets += [paths.config, paths.circles, paths.overrides]
    existing = [t for t in targets if t.exists()]
    if not existing:
        print("nothing to purge")
        return 0
    print("will delete:\n  " + "\n  ".join(map(str, existing)))
    if not args.yes and input("proceed? [y/N] ").strip().lower() != "y":
        return 1
    for h in list(log.handlers):
        log.removeHandler(h)
        h.close()
    for t in existing:
        shutil.rmtree(t) if t.is_dir() else t.unlink()
    print(
        "purged. The helper and the schedule stay: "
        "`lab radar helper uninstall`, `lab radar schedule uninstall`."
    )
    return 0


def helper_cmd(args) -> int:
    from light_labs.radar import doctor, helper

    paths, _ = _setup()
    try:
        if args.helper_cmd == "approve":
            return 0 if helper.approve(paths) else 1
        if args.helper_cmd == "build":
            out = helper.build(paths, args.snippets)
            print(f"built {out} from the approved source")
            print(doctor.FDA_STEPS.format(binary=out))
        elif args.helper_cmd == "install":
            print(f"installed {helper.install(paths)}")
        else:
            helper.uninstall()
            helper.binary_path(paths).unlink(missing_ok=True)
            print("uninstalled; remove radar-messages-export from Full Disk Access in Settings")
    except helper.NotApproved as e:
        print(e)
        return 1
    return 0


def schedule_cmd(args) -> int:
    from light_labs.radar import schedule

    paths, _ = _setup()
    if args.action == "install":
        try:
            installed = schedule.install(paths)
        except FileNotFoundError as e:
            print(e)
            return 1
        for p in installed:
            print(f"installed {p}")
    else:
        schedule.uninstall()
        print("removed the sync and weekly LaunchAgents")
    return 0
