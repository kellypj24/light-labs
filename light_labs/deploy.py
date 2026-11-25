"""`lab deploy`: run a service from a fixed commit instead of a live checkout.

Each deploy exports one commit of origin (`git archive`, no .git) into
<target>/releases/<sha>, installs it with `uv sync --locked`, then swaps <target>/current
to it in one rename. Services point at <target>/current and never see a half-built
release. Branch work in the checkout can't reach them; only a deploy can.

    lab deploy hermes                 origin/main
    lab deploy hermes --ref my-branch a branch, until main is deployed again
    lab deploy radar                  Radar's scheduled jobs and its page
    lab deploy lab                    Rush's tick and phone page, Dagster, Roll's chores
    lab deploy lab --rollback         back to the release before the current one

The `lab` target's launchd jobs (ops/*.plist) run <target>/current with LAB_VAR pointing at
the checkout's var/, so data stays where it was and only the code comes from a release.

`lab git land` redeploys a target that tracks main. A target on a branch stays put.
A deploy that changes the commit restarts the target's service (RESTART), since a running
process keeps the old release's code and config until it restarts.
"""

import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from light_labs import config

TARGETS = {
    # Rush (hourly tick, phone page), the Dagster daemon and Roll's chores: ops/*.plist.
    "lab": Path.home() / ".light-labs" / "lab",
    "hermes": Path.home() / ".hermes" / "lab",
    # Relationship Radar's scheduled sync and digest (light_labs/radar/schedule.py).
    "radar": Path.home() / ".relationship-radar" / "lab",
}
# Dependency groups a target's release installs on top of the project's own.
GROUPS = {"lab": ("orchestration",)}
# Git-ignored files a release reads from the main checkout; linked so edits there stay live.
LOCAL_FILES = (".env", "light_labs/agents/rush/memory.md")
STAMP = "DEPLOYED.json"
KEEP = 3
# `git fetch` over SSH drops now and then; wait 2 s, then 4 s, before giving up.
FETCH_TRIES, FETCH_WAIT = 3, 2
# Long-running launchd jobs that run the main checkout: a merge touching `paths` leaves
# them on the old code until `restart`. Rush's hourly tick is a new process each time.
SERVICES = {
    "rush-remote": {
        "label": "com.pjkelly.light-labs.rush-remote",
        "paths": ("light_labs/",),
        "restart": "launchctl kickstart -k gui/$(id -u)/com.pjkelly.light-labs.rush-remote",
    },
    "workouts": {
        "label": "com.pjkelly.light-labs.workouts",
        "paths": ("light_labs/",),
        "restart": "launchctl kickstart -k gui/$(id -u)/com.pjkelly.light-labs.workouts",
    },
    "dagster": {
        "label": "com.pjkelly.light-labs.dagster",
        "paths": ("light_labs/", "analytics/"),
        "restart": "just dagster-restart",
    },
}


def restart_lab(out=sys.stdout, run=subprocess.run, ps=None):
    """Put the `lab` target's long-running jobs on the new release. The phone page
    and Workouts restart; the Dagster daemon too unless a run is in progress (a restart would kill
    it), in which case this says how to do it later. A job launchd hasn't loaded is left."""
    from light_labs.core import heavy

    running = any(heavy.busy_kind(line) == "Dagster run" for line in heavy.processes(ps)[0])
    for name, service in SERVICES.items():
        if running_since(service["label"], run) is None:
            out.write(f"{name}: not running, left alone\n")
        elif name == "dagster" and running:
            out.write(f"dagster: a run is in progress; `{service['restart']}` when it ends\n")
        else:
            target = f"gui/{os.getuid()}/{service['label']}"
            done = run(["launchctl", "kickstart", "-k", target], capture_output=True, check=False)
            if done.returncode:
                raise DeployError(f"could not restart {name}: `{service['restart']}`")
            out.write(f"restarted: {name}\n")


# Radar's page (radar/schedule.py installs it). Named here, not imported: a deploy must
# not need Radar's dependencies.
RADAR_PAGE = "com.pjkelly.relationship-radar.page"


def restart_radar(out=sys.stdout, run=subprocess.run):
    """Put Radar's page on the new release; its sync and digest are a new process each
    run. Left alone when launchd hasn't loaded it."""
    if running_since(RADAR_PAGE, run) is None:
        out.write("radar page: not running, left alone\n")
        return
    target = f"gui/{os.getuid()}/{RADAR_PAGE}"
    done = run(["launchctl", "kickstart", "-k", target], capture_output=True, check=False)
    if done.returncode:
        raise DeployError(f"could not restart the radar page: `launchctl kickstart -k {target}`")
    out.write("restarted: radar page\n")


# What a deploy that changes the commit runs: a command, or a function of `out`.
# The Hermes gateway drains in-flight runs, then launchd starts it on the new release.
RESTART = {"hermes": ("hermes", "gateway", "restart"), "lab": restart_lab, "radar": restart_radar}


class DeployError(RuntimeError):
    pass


def _run(*cmd, cwd=None):
    done = subprocess.run(list(cmd), cwd=cwd, capture_output=True, check=False)
    if done.returncode:
        err = (done.stderr or done.stdout).decode(errors="replace").strip()
        raise DeployError(f"{' '.join(map(str, cmd[:3]))}: {err}")
    return done.stdout


def _fetch(source, sleep=time.sleep):
    for attempt in range(FETCH_TRIES):
        try:
            return _run("git", "-C", source, "fetch", "-q", "origin")
        except DeployError:
            if attempt == FETCH_TRIES - 1:
                raise
            sleep(FETCH_WAIT * 2**attempt)


def _is_ancestor(source, older, newer):
    """`older` is `newer` or one of its ancestors."""
    done = subprocess.run(
        ["git", "-C", str(source), "merge-base", "--is-ancestor", older, newer],
        capture_output=True,
        check=False,
    )
    return done.returncode == 0


def deployed(target):
    """The stamp of <target>/current, or None before the first deploy."""
    stamp = Path(target) / "current" / STAMP
    return json.loads(stamp.read_text()) if stamp.exists() else None


def _restart(restart, out):
    if callable(restart):
        restart(out)
        return "services"
    _run(*restart)
    return " ".join(restart)


def _main_checkout(source):
    """The repo's first checkout: where .env and Rush's memory live. `source` may be a
    worktree of it, which has neither."""
    listed = _run("git", "-C", source, "worktree", "list", "--porcelain").decode()
    return Path(listed.splitlines()[0].partition(" ")[2])


def _link_local(release, source):
    """Link LOCAL_FILES from the main checkout into `release`, replacing a missing or
    dangling link (a release built from a worktree that has since been removed)."""
    home = _main_checkout(source)
    for rel in LOCAL_FILES:
        link = release / rel
        if (home / rel).exists() and not link.exists():
            link.unlink(missing_ok=True)
            link.symlink_to(home / rel)


def deploy(
    target,
    ref="main",
    source=config.REPO,
    sync=True,
    restart=None,
    out=sys.stdout,
    sleep=time.sleep,
    groups=(),
    sha=None,
):
    """Export origin/<ref> (or `sha`, a commit on it) into a release, install it, point
    current at it, then run `restart` if the commit changed. Returns the stamp."""
    target, source = Path(target), Path(source)
    before = deployed(target)
    _fetch(source, sleep)
    head = _run("git", "-C", source, "rev-parse", "--verify", f"origin/{ref}^{{commit}}")
    head = head.decode().strip()
    if sha and not _is_ancestor(source, sha, head):
        raise DeployError(f"{sha[:12]} is not on origin/{ref}")
    sha = sha or head
    release = target / "releases" / sha[:12]
    if not (release / STAMP).exists():  # no stamp: never built, or a build that failed
        _run("rm", "-rf", release)
        release.mkdir(parents=True)
        try:
            _build(release, sha, source, sync, groups)
        except BaseException:
            _run("rm", "-rf", release)
            raise
    _link_local(release, source)
    stamp = {"ref": ref, "sha": sha, "deployed_at": datetime.now(UTC).isoformat(timespec="seconds")}
    (release / STAMP).write_text(json.dumps(stamp, indent=2) + "\n")
    link = target / "current.new"
    link.unlink(missing_ok=True)
    link.symlink_to(release.relative_to(target))
    os.replace(link, target / "current")
    _prune(target, keep=release)
    out.write(f"deployed {ref} {sha[:12]} -> {target / 'current'}\n")
    if restart and (before or {}).get("sha") != sha:
        _restart_after(restart, sha, out)
    return stamp


def _restart_after(restart, sha, out):
    try:
        what = _restart(restart, out)
    except (DeployError, OSError) as e:
        name = "the restart" if callable(restart) else f"`{' '.join(restart)}`"
        raise DeployError(f"deployed {sha[:12]}, but {name} failed: {e}") from e
    if not callable(restart):
        out.write(f"restarted: {what}\n")


def rollback(target, restart=None, out=sys.stdout):
    """Point <target>/current at the release deployed before it, and restart. The next
    deploy (or `lab git land`, for a target on main) moves it forward again."""
    target = Path(target)
    current = (target / "current").resolve()

    def when(p):
        return json.loads((p / STAMP).read_text())["deployed_at"]

    older = [
        p
        for p in (target / "releases").iterdir()
        if (p / STAMP).exists() and p.resolve() != current and when(p) < when(current)
    ]
    if not older:
        raise DeployError("no earlier release to go back to")
    release = max(older, key=when)
    link = target / "current.new"
    link.unlink(missing_ok=True)
    link.symlink_to(release.relative_to(target))
    os.replace(link, target / "current")
    stamp = json.loads((release / STAMP).read_text())
    out.write(f"rolled back to {stamp['ref']} {stamp['sha'][:12]} -> {target / 'current'}\n")
    if restart:
        _restart_after(restart, stamp["sha"], out)
    return stamp


def _build(release, sha, source, sync, groups=()):
    archive = _run("git", "-C", source, "archive", "--format=tar", sha)
    with tempfile.TemporaryFile() as tmp:
        tmp.write(archive)
        tmp.seek(0)
        with tarfile.open(fileobj=tmp) as tar:
            tar.extractall(release, filter="data")
    if sync:
        extra = [arg for group in groups for arg in ("--group", group)]
        _run("uv", "sync", "--locked", "--no-dev", *extra, "--project", release)


def _prune(target, keep):
    """Drop all but the KEEP most recently deployed releases; never the current one."""

    def when(p):
        return (p / STAMP).stat().st_mtime if (p / STAMP).exists() else 0

    releases = sorted((target / "releases").iterdir(), key=when)
    for old in releases[:-KEEP]:
        if old != keep:
            _run("rm", "-rf", old)


def redeploy_main(main, out=sys.stdout, sha=None, source=config.REPO, **kw):
    """After a merge to main: redeploy every target that tracks it. Returns the names.
    With `sha` (the merge whose CI passed), deploy that commit, not whatever main has
    reached since, and leave a target already at or past it. One target failing doesn't
    stop the others; DeployError then names each that failed."""
    done, failed = [], []
    for name, target in TARGETS.items():
        stamp = deployed(target)
        if stamp and stamp["ref"] == main and sha and _is_ancestor(source, sha, stamp["sha"]):
            out.write(f"{name} is already at or past {sha[:12]}\n")
        elif stamp and stamp["ref"] == main:
            try:
                deploy(
                    target,
                    main,
                    restart=RESTART.get(name),
                    out=out,
                    groups=GROUPS.get(name, ()),
                    sha=sha,
                    source=source,
                    **kw,
                )
            except DeployError as e:
                failed.append(f"{name}: {e} (retry: `lab deploy {name}`)")
            else:
                done.append(name)
        elif stamp:
            out.write(f"{name} stays on {stamp['ref']} ({stamp['sha'][:12]})\n")
    if failed:
        raise DeployError("; ".join(failed))
    return done


def running_since(label, run=subprocess.run):
    """When launchd job `label`'s process started, or None when it isn't running."""
    listed = run(["launchctl", "list", label], capture_output=True, text=True, check=False)
    pid = next(
        (
            line.split("=")[1].strip(" ;")
            for line in listed.stdout.splitlines()
            if line.strip().startswith('"PID"')
        ),
        None,
    )
    if listed.returncode or not pid:
        return None
    started = run(["ps", "-o", "lstart=", "-p", pid], capture_output=True, text=True, check=False)
    try:
        return datetime.strptime(" ".join(started.stdout.split()), "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None


def stale_services(files, run=subprocess.run):
    """[(name, started, restart command)] for the running services a merge of `files`
    left on the old code."""
    out = []
    for name, service in SERVICES.items():
        if any(f.startswith(service["paths"]) for f in files):
            since = running_since(service["label"], run)
            if since:
                out.append((name, since, service["restart"]))
    return out
