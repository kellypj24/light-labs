"""`lab deploy`: run a service from a fixed commit instead of a live checkout.

Each deploy exports one commit of origin (`git archive`, no .git) into
<target>/releases/<sha>, installs it with `uv sync --locked`, then swaps <target>/current
to it in one rename. Services point at <target>/current and never see a half-built
release. Branch work in the checkout can't reach them; only a deploy can.

    lab deploy hermes                 origin/main
    lab deploy hermes --ref my-branch a branch, until main is deployed again

`lab git land` redeploys a target that tracks main. A target on a branch stays put.
"""

import json
import os
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from light_labs import config

TARGETS = {"hermes": Path.home() / ".hermes" / "lab"}
# Git-ignored files a release reads from the checkout; linked so edits there stay live.
LOCAL_FILES = (".env", "light_labs/agents/rush/memory.md")
STAMP = "DEPLOYED.json"
KEEP = 3


class DeployError(RuntimeError):
    pass


def _run(*cmd, cwd=None):
    done = subprocess.run(list(cmd), cwd=cwd, capture_output=True, check=False)
    if done.returncode:
        err = (done.stderr or done.stdout).decode(errors="replace").strip()
        raise DeployError(f"{' '.join(map(str, cmd[:3]))}: {err}")
    return done.stdout


def deployed(target):
    """The stamp of <target>/current, or None before the first deploy."""
    stamp = Path(target) / "current" / STAMP
    return json.loads(stamp.read_text()) if stamp.exists() else None


def deploy(target, ref="main", source=config.REPO, sync=True, out=sys.stdout):
    """Export origin/<ref> into a release, install it, point current at it. Returns the stamp."""
    target, source = Path(target), Path(source)
    _run("git", "-C", source, "fetch", "-q", "origin")
    sha = _run("git", "-C", source, "rev-parse", "--verify", f"origin/{ref}^{{commit}}")
    sha = sha.decode().strip()
    release = target / "releases" / sha[:12]
    if not (release / STAMP).exists():  # no stamp: never built, or a build that failed
        _run("rm", "-rf", release)
        release.mkdir(parents=True)
        try:
            _build(release, sha, source, sync)
        except BaseException:
            _run("rm", "-rf", release)
            raise
    stamp = {"ref": ref, "sha": sha, "deployed_at": datetime.now(UTC).isoformat(timespec="seconds")}
    (release / STAMP).write_text(json.dumps(stamp, indent=2) + "\n")
    link = target / "current.new"
    link.unlink(missing_ok=True)
    link.symlink_to(release.relative_to(target))
    os.replace(link, target / "current")
    _prune(target, keep=release)
    out.write(f"deployed {ref} {sha[:12]} -> {target / 'current'}\n")
    return stamp


def _build(release, sha, source, sync):
    archive = _run("git", "-C", source, "archive", "--format=tar", sha)
    with tempfile.TemporaryFile() as tmp:
        tmp.write(archive)
        tmp.seek(0)
        with tarfile.open(fileobj=tmp) as tar:
            tar.extractall(release, filter="data")
    for rel in LOCAL_FILES:
        if (source / rel).exists():
            (release / rel).symlink_to(source / rel)
    if sync:
        _run("uv", "sync", "--locked", "--no-dev", "--project", release)


def _prune(target, keep):
    """Drop all but the KEEP most recently deployed releases; never the current one."""

    def when(p):
        return (p / STAMP).stat().st_mtime if (p / STAMP).exists() else 0

    releases = sorted((target / "releases").iterdir(), key=when)
    for old in releases[:-KEEP]:
        if old != keep:
            _run("rm", "-rf", old)


def redeploy_main(main, out=sys.stdout, **kw):
    """After a merge to main: redeploy every target that tracks it. Returns the names."""
    done = []
    for name, target in TARGETS.items():
        stamp = deployed(target)
        if stamp and stamp["ref"] == main:
            deploy(target, main, out=out, **kw)
            done.append(name)
        elif stamp:
            out.write(f"{name} stays on {stamp['ref']} ({stamp['sha'][:12]})\n")
    return done
