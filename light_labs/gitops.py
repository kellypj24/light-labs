"""`lab git`: the git and GitHub chores, one command each, compact output.

    status  branch, working tree, open PRs with CI state, Dependabot alerts
    ship    run the repo's check, commit, push, open (or find) the PR
    land    wait for CI, squash-merge, update main, delete the branch
    tidy    branches and worktrees whose work is merged or abandoned; --apply deletes
    labels  sync the repo's label set from .github/labels.toml; --apply writes
    label   label a PR (or every open one): type from its title, areas from its paths

Works in any repo with an `origin` on GitHub and `gh` logged in. No model involved: these
replace multi-step tool sequences. Drafting messages is a separate (robot) job.
"""

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MAIN_NAMES = ("main", "master")


class GitError(RuntimeError):
    pass


class Repo:
    def __init__(self, path=".", run=subprocess.run):
        self.path = Path(path)
        self._run = run

    def sh(self, *cmd, check=True, env=None):
        done = self._run(
            list(cmd), cwd=self.path, capture_output=True, text=True, check=False, env=env
        )
        if check and done.returncode:
            raise GitError(f"{' '.join(cmd[:3])}: {(done.stderr or done.stdout).strip()}")
        return done.stdout.strip()

    def git(self, *args, check=True):
        return self.sh("git", *args, check=check)

    def gh(self, *args, check=True):
        return self.sh("gh", *args, check=check)

    def gh_json(self, *args):
        out = self.gh(*args)
        return json.loads(out) if out else []

    def branch(self):
        return self.git("branch", "--show-current")

    def main_branch(self):
        ref = self.git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
        if ref:
            return ref.split("/", 1)[1]
        local = self.git("branch", "--format=%(refname:short)").split()
        return next((b for b in MAIN_NAMES if b in local), "main")

    def dirty(self):
        return [line for line in self.git("status", "--porcelain").splitlines() if line]


# --- status -----------------------------------------------------------------------------


def checks_state(rollup):
    """pass / fail / pending / none from a PR's statusCheckRollup."""
    if not rollup:
        return "none"
    states = []
    for c in rollup:
        if c.get("status") not in (None, "COMPLETED"):
            states.append("pending")
            continue
        verdict = c.get("conclusion") or c.get("state") or ""
        if verdict in ("SUCCESS", "NEUTRAL", "SKIPPED"):
            states.append("pass")
        elif verdict in ("PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", ""):
            states.append("pending")
        else:
            states.append("fail")
    for s in ("fail", "pending"):
        if s in states:
            return s
    return "pass"


CHANGED_SHOWN = 8


def _check_name(c):
    return c.get("name") or c.get("context") or "?"


def failing_checks(rollup):
    """Names of the checks in a statusCheckRollup that failed."""
    return [_check_name(c) for c in rollup or [] if checks_state([c]) == "fail"]


def worktrees(repo):
    """[{path, branch, head}] for every worktree; branch is None when detached."""
    out = []
    for block in repo.git("worktree", "list", "--porcelain").split("\n\n"):
        fields = dict((line.split(" ", 1) + [""])[:2] for line in block.splitlines())
        if "worktree" in fields:
            branch = fields.get("branch", "").removeprefix("refs/heads/") or None
            out.append({"path": fields["worktree"], "branch": branch, "head": fields.get("HEAD")})
    return out


def _counts(repo, path, ref):
    """(behind, ahead) of HEAD in `path` against `ref`, or None when `ref` is missing."""
    got = repo.sh("git", "-C", path, "rev-list", "--left-right", "--count", f"{ref}...HEAD",
                  check=False)  # fmt: skip
    parts = got.split()
    return (int(parts[0]), int(parts[1])) if len(parts) == 2 else None


def _home(path):
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home) else path


def _pr_line(pr):
    """'#12 open, checks pass: title' for a PR from `gh pr list --json`."""
    state = pr["state"].lower()
    if pr["state"] == "OPEN":
        state += f", checks {checks_state(pr.get('statusCheckRollup'))}"
        if pr.get("isDraft"):
            state += ", draft"
    return f"#{pr['number']} {state}: {pr['title'][:60]}"


def status(repo, pr=None, fetch=True, out=sys.stdout):
    """One look at where the work stands, instead of git status/log/branch/worktree list
    and gh pr view/checks: this checkout, every other worktree with its PR, open PRs.
    With `pr`, that PR in detail."""
    if fetch:
        repo.git("fetch", "-q", "--prune", "origin", check=False)
    if pr is not None:
        return pr_status(repo, pr, out)
    main = repo.main_branch()
    prs = repo.gh_json(
        "pr", "list", "--state", "all", "--limit", "60", "--json",
        "number,title,headRefName,state,statusCheckRollup,isDraft",
    )  # fmt: skip
    by_branch = _pr_by_branch(prs)
    here = str(Path(repo.git("rev-parse", "--show-toplevel")).resolve())

    branch = repo.branch()
    where = branch or f"detached at {repo.git('rev-parse', '--short', 'HEAD')}"
    dirty = repo.dirty()
    line = f"{_home(here)} on {where}: {len(dirty)} changed"
    counts = _counts(repo, here, f"origin/{main}")
    if counts:
        line += f", {counts[1]} ahead / {counts[0]} behind origin/{main}"
    if branch and branch != main:
        upstream = _counts(repo, here, "@{u}")
        line += (
            f", upstream {upstream[1]} ahead / {upstream[0]} behind" if upstream
            else ", not pushed"
        )  # fmt: skip
    out.write(line + "\n")
    out.write(f"last: {repo.git('log', '-1', '--format=%h %s (%cr)')}\n")
    for change in dirty[:CHANGED_SHOWN]:
        out.write(f"  {change}\n")
    if len(dirty) > CHANGED_SHOWN:
        out.write(f"  ... {len(dirty) - CHANGED_SHOWN} more\n")
    if branch in by_branch:
        out.write(f"PR {_pr_line(by_branch[branch])}\n")

    others = [w for w in worktrees(repo) if str(Path(w["path"]).resolve()) != here]
    if others:
        out.write("\nworktrees\n")
        for w in others:
            name = w["branch"] or f"detached at {(w['head'] or '')[:7]}"
            changed = repo.sh("git", "-C", w["path"], "status", "--porcelain", check=False)
            parts = [f"{len(changed.splitlines())} changed"]
            counts = _counts(repo, w["path"], f"origin/{main}")
            if counts:
                parts.append(f"{counts[1]} ahead")
            found = by_branch.get(w["branch"])
            if found:
                parts.append(_pr_line(found))
                if found["state"] == "MERGED" and not changed:
                    parts.append("`lab git tidy` removes it")
            elif w["branch"] is None and counts and counts[1] == 0 and not changed:
                parts.append("`lab git tidy` removes it")
            out.write(f"  {_home(w['path'])} [{name}] {' · '.join(parts)}\n")

    open_prs = [p for p in prs if p["state"] == "OPEN"]
    if open_prs:
        out.write("\nopen PRs\n")
        for p in open_prs:
            mark = "*" if p["headRefName"] == branch else " "
            out.write(f" {mark}{_pr_line(p)} [{p['headRefName'][:28]}]\n")
            failed = failing_checks(p.get("statusCheckRollup"))
            if failed:
                out.write(f"     failing: {', '.join(failed)}\n")
    else:
        out.write("\nno open PRs\n")
    alerts = alerts_summary(repo)
    if alerts:
        out.write(f"\ndependabot: {alerts}\n")


def pr_status(repo, number, out=sys.stdout):
    """One PR: state, branch, mergeability, review, every check, and its merge commit."""
    pr = repo.gh_json(
        "pr", "view", str(number), "--json",
        "number,title,state,headRefName,baseRefName,mergeable,mergeStateStatus,"
        "reviewDecision,statusCheckRollup,mergeCommit,isDraft,url",
    )  # fmt: skip
    out.write(f"{_pr_line(pr)}\n{pr['headRefName']} -> {pr['baseRefName']}  {pr['url']}\n")
    if pr["state"] == "MERGED":
        commit = (pr.get("mergeCommit") or {}).get("oid", "")[:7]
        out.write(f"merged as {commit}\n")
    elif pr["state"] == "OPEN":
        review = (pr.get("reviewDecision") or "none").lower().replace("_", " ")
        out.write(
            f"mergeable: {pr['mergeable'].lower()} ({pr['mergeStateStatus'].lower()}), "
            f"review: {review}\n"
        )
    rollup = pr.get("statusCheckRollup") or []
    tally = {}
    for c in rollup:
        tally[checks_state([c])] = tally.get(checks_state([c]), 0) + 1
    if rollup:
        out.write("checks: " + ", ".join(f"{n} {s}" for s, n in sorted(tally.items())) + "\n")
        for c in rollup:
            verdict = checks_state([c])
            if verdict != "pass":
                link = c.get("detailsUrl") or c.get("targetUrl") or ""
                out.write(f"  {verdict:7} {_check_name(c)}  {link}\n")
    else:
        out.write("checks: none\n")


def alerts_summary(repo):
    """'2 open (2 high): sqlfluff' or '' (none, or no access)."""
    try:
        alerts = repo.gh_json(
            "api", "repos/{owner}/{repo}/dependabot/alerts?state=open&per_page=100"
        )
    except (GitError, json.JSONDecodeError):
        return ""
    if not alerts:
        return ""
    sev = {}
    for a in alerts:
        s = a["security_advisory"]["severity"]
        sev[s] = sev.get(s, 0) + 1
    names = sorted({a["dependency"]["package"]["name"] for a in alerts})
    counts = ", ".join(f"{n} {s}" for s, n in sorted(sev.items()))
    return f"{len(alerts)} open ({counts}): {', '.join(names)}"


# --- ship -------------------------------------------------------------------------------


def default_check(repo):
    justfile = repo.path / "justfile"
    if justfile.exists() and re.search(r"^check\b.*:", justfile.read_text(), re.MULTILINE):
        return ["just", "check"]
    return None


def ship(repo, message=None, title=None, body=None, check=None, out=sys.stdout):
    """Check, commit, push, PR. Returns the PR URL."""
    branch = repo.branch()
    if branch in MAIN_NAMES or branch == repo.main_branch():
        raise GitError(f"on {branch}: branch first")
    check = check or default_check(repo)
    if not check:
        raise GitError("no check to run: pass --check '<command>' (no justfile `check`)")
    dirty = repo.dirty()
    if dirty and not message:
        raise GitError(f"{len(dirty)} changed file(s) and no commit message (-m / -F)")
    out.write(f"check: {' '.join(check)} ... ")
    out.flush()
    started = time.monotonic()
    done = subprocess.run(check, cwd=repo.path, capture_output=True, text=True, check=False)
    if done.returncode:
        out.write("FAILED\n")
        tail = (done.stdout + done.stderr).strip().splitlines()[-40:]
        out.write("\n".join(tail) + "\n")
        raise GitError("check failed; nothing committed or pushed")
    out.write(f"ok ({time.monotonic() - started:.0f}s)\n")
    if dirty:
        repo.git("add", "-A")
        repo.git("commit", "-q", "-m", message)
        out.write(f"commit: {repo.git('log', '-1', '--format=%h %s')}\n")
        for line in repo.git("show", "--stat", "--format=", "HEAD").splitlines()[-1:]:
            out.write(f"        {line.strip()}\n")
    repo.git("push", "-q", "-u", "origin", "HEAD")
    out.write(f"push: origin/{branch}\n")
    existing = repo.gh_json("pr", "list", "--head", branch, "--json", "number,url")
    if existing:
        url = existing[0]["url"]
        out.write(f"pr: {url} (updated)\n")
        return url
    subject = repo.git("log", "-1", "--format=%s")
    if body is None:
        commit_body = repo.git("log", "-1", "--format=%b").strip()
        body = f"## Summary\n{commit_body}\n\n## Test plan\n- `{' '.join(check)}`\n"
    url = repo.gh("pr", "create", "--title", title or subject, "--body", body).splitlines()[-1]
    out.write(f"pr: {url}\n")
    label_prs(repo, [url.rsplit("/", 1)[-1]], out=out)
    return url


# --- land -------------------------------------------------------------------------------


def wait_for_checks(repo, pr, timeout=1800, every=20, sleep=time.sleep):
    """The PR's checks once none is pending (or the timeout passes)."""
    deadline = time.monotonic() + timeout
    while True:
        checks = repo.gh_json("pr", "checks", str(pr), "--json", "name,bucket,link")
        if checks and all(c["bucket"] != "pending" for c in checks):
            return checks
        if time.monotonic() > deadline:
            raise GitError(f"#{pr}: checks still pending after {timeout // 60} min")
        sleep(every)


def failure_report(repo, checks):
    failed = [c for c in checks if c["bucket"] in ("fail", "cancel")]
    lines = [f"failed: {', '.join(c['name'] for c in failed)}"]
    for c in failed:
        m = re.search(r"/actions/runs/(\d+)", c.get("link", ""))
        if m:
            log = repo.gh("run", "view", m.group(1), "--log-failed", check=False)
            tail = [line.split("\t")[-1] for line in log.splitlines()[-30:]]
            lines += [f"--- {c['name']} (run {m.group(1)}), last lines:", *tail]
            break
    return "\n".join(lines)


def land(repo, pr, wait=True, out=sys.stdout, sleep=time.sleep):
    info = repo.gh_json("pr", "view", str(pr), "--json", "state,headRefName,title,files")
    if info["state"] != "OPEN":
        raise GitError(f"#{pr} is {info['state'].lower()}")
    if wait:
        out.write(f"#{pr}: waiting for CI ... ")
        out.flush()
        checks = wait_for_checks(repo, pr, sleep=sleep)
        if any(c["bucket"] in ("fail", "cancel") for c in checks):
            out.write("FAILED\n" + failure_report(repo, checks) + "\n")
            raise GitError(f"#{pr} not merged")
        out.write(f"green ({len(checks)} checks)\n")
    # Merge and delete the branch on GitHub only: `gh pr merge --delete-branch` also
    # switches this checkout to main, which git refuses while another worktree has it.
    repo.gh("pr", "merge", str(pr), "--squash")
    head = info["headRefName"]
    repo.gh("api", "-X", "DELETE", f"repos/{{owner}}/{{repo}}/git/refs/heads/{head}", check=False)
    main = repo.main_branch()
    repo.git("fetch", "-q", "--prune", "origin")
    held = _worktree_of(repo, main)
    if repo.branch() == head:
        if held:
            repo.git("checkout", "-q", "--detach", f"origin/{main}")
        else:
            repo.git("checkout", "-q", main)
    if repo.branch() == main:
        repo.git("merge", "-q", "--ff-only", f"origin/{main}")
    kept = _worktree_of(repo, head)
    if not kept:
        repo.git("branch", "-D", head, check=False)
    out.write(f"merged #{pr}: {repo.git('log', '-1', '--format=%h %s', f'origin/{main}')}\n")
    where = repo.branch() or f"origin/{main}, detached ({main} is checked out in {held})"
    gone = f"kept {head} (checked out in {kept})" if kept else f"deleted {head}"
    out.write(f"on {where}; {gone}\n")
    return [f["path"] for f in info.get("files", [])]


def _worktree_of(repo, branch):
    """Path of another worktree that has `branch` checked out, or None."""
    here = Path(repo.git("rev-parse", "--show-toplevel")).resolve()
    for block in repo.git("worktree", "list", "--porcelain").split("\n\n"):
        fields = dict(line.partition(" ")[::2] for line in block.splitlines())
        path = Path(fields.get("worktree", "")).resolve()
        if fields.get("branch") == f"refs/heads/{branch}" and path != here:
            return str(path)
    return None


# --- tidy -------------------------------------------------------------------------------


@dataclass
class Action:
    kind: str  # local, remote, worktree
    target: str
    reason: str
    delete: bool  # False: listed for a person to decide


def _pr_by_branch(prs):
    """Latest PR per head branch."""
    out = {}
    for pr in sorted(prs, key=lambda p: p["number"]):
        out[pr["headRefName"]] = pr
    return out


def _age_days(iso, now):
    return (now - datetime.fromisoformat(iso)).days if iso else None


def plan_tidy(repo, prs, now=None, stale_days=30):
    """What tidy would do. Deletes only work that is merged, or pushed in a PR closed more
    than `stale_days` ago (GitHub keeps refs/pull/<n>/head, so it stays recoverable).
    Branches with no PR are only listed: they may hold work nobody has seen. A detached
    worktree (`land` leaves one at origin/<main>) goes when its HEAD is on main."""
    now = now or datetime.now(UTC)
    main = repo.main_branch()
    current = repo.branch()
    by_branch = _pr_by_branch(prs)
    actions = []

    worktrees, locked, detached = {}, {}, {}
    for block in repo.git("worktree", "list", "--porcelain").split("\n\n"):
        fields = dict((line.split(" ", 1) + [""])[:2] for line in block.splitlines())
        if "locked" in fields:
            locked[fields["worktree"]] = fields["locked"] or "no reason given"
        if "branch" in fields:
            worktrees[fields["branch"].removeprefix("refs/heads/")] = fields["worktree"]
        elif "detached" in fields:
            detached[fields["worktree"]] = fields["HEAD"]
    primary = str(repo.path.resolve())

    def ahead(sha, ref=main):
        got = repo.git("rev-list", "--count", f"{ref}..{sha}", check=False)
        return int(got) if got.isdigit() else float("inf")

    def contained(sha, ref=main):
        return ahead(sha, ref) == 0

    def verdict(branch, sha):
        pr = by_branch.get(branch)
        if pr and pr["state"] == "MERGED":
            if pr.get("headRefOid") not in (None, sha) and not contained(sha):
                return False, f"PR #{pr['number']} merged, but the branch moved after"
            return True, f"PR #{pr['number']} merged"
        if pr and pr["state"] == "CLOSED":
            days = _age_days(pr.get("closedAt"), now)
            if days is not None and days >= stale_days:
                return True, f"PR #{pr['number']} closed unmerged {days}d ago"
            return False, f"PR #{pr['number']} closed unmerged {days}d ago (< {stale_days}d)"
        if pr:
            return None, None  # open PR: leave alone
        if contained(sha):
            return True, f"no PR, already in {main}"
        return False, "no PR"

    for line in repo.git(
        "for-each-ref", "--format=%(refname:short)|%(objectname)|%(upstream:track)", "refs/heads"
    ).splitlines():
        branch, sha, track = line.split("|", 2)
        if branch in (main, current):
            continue
        delete, reason = verdict(branch, sha)
        if delete is None:
            continue
        if not delete and "[gone]" in track:
            reason += "; upstream deleted"
        if branch in worktrees and worktrees[branch] != primary:
            path = worktrees[branch]
            dirty = repo.sh("git", "-C", path, "status", "--porcelain", check=False)
            if delete and not dirty and path not in locked:
                actions.append(Action("worktree", path, f"{branch}: {reason}", True))
            else:
                why = (
                    "uncommitted changes"
                    if dirty
                    else f"locked ({locked[path]}); {reason}"
                    if path in locked
                    else reason
                )
                actions.append(Action("worktree", path, f"{branch}: {why}", False))
                continue
        if not delete:
            unique = repo.git("rev-list", "--count", f"{main}..{branch}", check=False)
            reason += f", {unique or '?'} commit(s) not on {main}"
        actions.append(Action("local", branch, reason, delete))

    for path, head in detached.items():
        if str(Path(path).resolve()) == primary:
            continue
        dirty = repo.sh("git", "-C", path, "status", "--porcelain", check=False)
        # origin/<main> too: local main lags after `land` in another worktree
        on_main = contained(head) or contained(head, f"origin/{main}")
        where = f"detached at {head[:7]}"
        if on_main and not dirty and path not in locked:
            actions.append(Action("worktree", path, f"{where}: already in {main}", True))
            continue
        why = (
            "uncommitted changes"
            if dirty
            else f"locked ({locked[path]})"
            if path in locked
            else f"{min(ahead(head, ref) for ref in (main, f'origin/{main}'))} commit(s) not on {main}"
        )
        actions.append(Action("worktree", path, f"{where}: {why}", False))

    for ref in repo.git(
        "for-each-ref",
        "--format=%(refname)|%(objectname)|%(committerdate:iso-strict)",
        "refs/remotes/origin",
    ).splitlines():
        name, sha, date = ref.split("|", 2)
        branch = name.removeprefix("refs/remotes/origin/")
        if branch in (main, "HEAD"):
            continue
        delete, reason = verdict(branch, sha)
        if delete is None:
            continue
        if not delete:
            reason += f", last commit {_age_days(date, now)}d ago"
            if reason.startswith("no PR") and _age_days(date, now) < stale_days:
                continue  # recent pushes without a PR yet are normal
        actions.append(Action("remote", branch, reason, delete))
    return actions


def apply_tidy(repo, actions, out=sys.stdout):
    """Delete the delete rows. One failure doesn't stop the rest; returns the failures."""
    failed = []
    for a in actions:
        if not a.delete:
            continue
        try:
            if a.kind == "worktree":
                repo.git("worktree", "remove", a.target)
            elif a.kind == "local":
                repo.git("branch", "-D", a.target)
            elif a.kind == "remote":
                repo.git("push", "-q", "origin", "--delete", a.target)
        except GitError as e:
            failed.append(a)
            out.write(f"FAILED  {a.kind} {a.target}: {str(e).splitlines()[0]}\n")
            continue
        out.write(f"deleted {a.kind} {a.target}\n")
    repo.git("worktree", "prune")
    return failed


def tidy(repo, apply=False, stale_days=30, out=sys.stdout):
    repo.git("fetch", "-q", "--prune")
    prs = repo.gh_json(
        "pr", "list", "--state", "all", "--limit", "500",
        "--json", "number,headRefName,headRefOid,state,closedAt",
    )  # fmt: skip
    actions = plan_tidy(repo, prs, stale_days=stale_days)
    if not actions:
        out.write("nothing to tidy\n")
        return actions
    for a in actions:
        verb = ("delete" if apply else "would delete") if a.delete else "review"
        out.write(f"{verb:12} {a.kind:8} {a.target:40} {a.reason}\n")
    if apply:
        if apply_tidy(repo, actions, out):
            raise GitError("some deletions failed; see FAILED rows")
    elif any(a.delete for a in actions):
        out.write("\nlab git tidy --apply deletes the first kind; `review` rows are yours.\n")
    return actions


# --- labels -----------------------------------------------------------------------------

LABELS_FILE = ".github/labels.toml"


def load_labels(repo):
    """{name: {color, description, paths?}} from .github/labels.toml, or None without one.

    [types.<type>] become `type: <type>`; [areas.<area>] (with `paths` prefixes) become
    `area: <area>`; [states.<state>] become `state: <state>` (issue states, never set by
    `ship`/`label`); [keep].labels are labels other tools set (Dependabot), left alone."""
    import tomllib

    path = repo.path / LABELS_FILE
    if not path.exists():
        return None
    data = tomllib.loads(path.read_text())
    labels = {}
    for kind in ("types", "areas", "states"):
        for key, spec in data.get(kind, {}).items():
            labels[f"{kind[:-1]}: {key}"] = spec
    return labels, set(data.get("keep", {}).get("labels", []))


def sync_labels(repo, apply=False, prune=False, out=sys.stdout):
    """Create or update the file's labels; with prune, delete labels the file doesn't name
    (GitHub's unused defaults). Returns the planned changes."""
    loaded = load_labels(repo)
    if loaded is None:
        raise GitError(f"no {LABELS_FILE} in {repo.path}")
    wanted, keep = loaded
    have = {
        label["name"]: label
        for label in repo.gh_json(
            "label", "list", "--limit", "200", "--json", "name,color,description"
        )
    }
    changes = []
    for name, spec in wanted.items():
        color, desc = spec["color"].lower(), spec.get("description", "")
        if name not in have:
            changes.append(("create", name, ["label", "create", name, "-c", color, "-d", desc]))
        elif (have[name]["color"].lower(), have[name]["description"]) != (color, desc):
            changes.append(("update", name, ["label", "edit", name, "-c", color, "-d", desc]))
    if prune:
        for name in sorted(set(have) - set(wanted) - keep):
            changes.append(("delete", name, ["label", "delete", name, "--yes"]))
    if not changes:
        out.write("labels in sync\n")
    for verb, name, args in changes:
        out.write(f"{verb if apply else 'would ' + verb:14} {name}\n")
        if apply:
            repo.gh(*args)
    return changes


def labels_for(title, paths, labels):
    """Labels a PR should carry: its conventional type, and every area a path falls in."""
    out = []
    m = re.match(r"^(\w+)(\([^)]*\))?!?:", title)
    if m and f"type: {m.group(1)}" in labels:
        out.append(f"type: {m.group(1)}")
    for name, spec in labels.items():
        if name.startswith("area: ") and any(
            p.startswith(prefix) for p in paths for prefix in spec.get("paths", [])
        ):
            out.append(name)
    return out


def label_prs(repo, prs=None, out=sys.stdout):
    """Add the missing type/area labels to the given PRs, or to every open PR. Never
    removes a label someone set."""
    loaded = load_labels(repo)
    if loaded is None:
        return {}
    labels, _ = loaded
    if prs is None:
        prs = [p["number"] for p in repo.gh_json("pr", "list", "--json", "number")]
    on_github = {
        x["name"] for x in repo.gh_json("label", "list", "--limit", "200", "--json", "name")
    }
    added = {}
    for pr in prs:
        info = repo.gh_json("pr", "view", str(pr), "--json", "title,files,labels")
        have = {label["name"] for label in info["labels"]}
        paths = [f["path"] for f in info["files"]]
        wanted = [x for x in labels_for(info["title"], paths, labels) if x not in have]
        unsynced = [x for x in wanted if x not in on_github]
        if unsynced:
            out.write(f"#{pr}: not on GitHub yet ({', '.join(unsynced)}): lab git labels --apply\n")
        missing = [x for x in wanted if x in on_github]
        if missing:
            repo.gh("pr", "edit", str(pr), "--add-label", ",".join(missing))
            out.write(f"#{pr}: + {', '.join(missing)}\n")
        added[pr] = missing
    return added
