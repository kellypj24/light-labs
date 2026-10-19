"""Rush's GitHub watch: rules, no model. Tells PJ about CI, Dependabot and PR comments.

Each tick asks `gh` (already logged in) about PJ's active repos and texts him at most one
message over the phone channel (phone.py / telegram.py): the one event, or a digest.

Events, each only when new since the last check:
- CI on the default branch: a workflow's latest completed run failed after passing, or
  passed again after failing (transitions only, so a broken main is one message, not one
  an hour).
- Dependabot PRs that opened since the last check, one line per repo.
- Comments and reviews on PJ's open PRs by someone other than PJ or a bot.

A repo seen for the first time is recorded without messages, like the board scan. In
quiet hours nothing is checked; the next tick after catches up. State: github.json in
Rush's var dir.
"""

import json
import subprocess
from datetime import UTC, datetime, timedelta

from light_labs.agents.rush.phone import PREFIX, quiet

ACTIVE_DAYS = 30
MAX_LINES = 8
FAILED = {"failure", "timed_out", "startup_failure"}
BOTS = {"github-actions", "dependabot", "copilot"}


def gh(args, run=subprocess.run):
    """JSON from one `gh` call. Raises OSError or CalledProcessError on failure."""
    out = run(["gh", *args], capture_output=True, text=True, check=True, timeout=60)
    return json.loads(out.stdout or "null")


def _is_bot(login):
    login = (login or "").lower()
    return login.endswith("[bot]") or login in BOTS


class Watch:
    def __init__(self, store, repos=None, run=subprocess.run, now=None):
        self.store, self.repos, self.run = store, repos or [], run
        self.now = now or datetime.now(UTC)
        self.path = store.root / "github.json"

    def _gh(self, *args):
        return gh(list(args), self.run)

    def _state(self):
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"repos": {}}

    def active_repos(self, me):
        if self.repos:
            return [(r, None) for r in self.repos]
        listed = self._gh(
            "repo",
            "list",
            me,
            "--no-archived",
            "--limit",
            "100",
            "--json",
            "nameWithOwner,pushedAt,defaultBranchRef",
        )
        cutoff = self.now - timedelta(days=ACTIVE_DAYS)
        return [
            (r["nameWithOwner"], (r.get("defaultBranchRef") or {}).get("name"))
            for r in listed
            if r.get("pushedAt") and datetime.fromisoformat(r["pushedAt"]) >= cutoff
        ]

    # --- one repo: events since `seen`, and the new `seen`
    def _ci(self, repo, branch, seen):
        if not branch:
            branch = self._gh("repo", "view", repo, "--json", "defaultBranchRef")[
                "defaultBranchRef"
            ]["name"]
        runs = self._gh(
            "run", "list", "-R", repo, "--branch", branch, "--status", "completed",
            "--limit", "20", "--json", "databaseId,conclusion,workflowName,url",
        )  # fmt: skip
        latest = {}
        for r in runs:  # newest first: the first run per workflow is its latest
            latest.setdefault(r["workflowName"], r)
        events, now = [], {}
        for name, r in latest.items():
            failing = r["conclusion"] in FAILED
            now[name] = {"run": r["databaseId"], "failing": failing}
            before = seen.get(name)
            if before is None or before["run"] == r["databaseId"]:
                continue
            if failing and not before["failing"]:
                events.append(f"CI failed on {repo} {branch} ({name}): {r['url']}")
            elif not failing and before["failing"]:
                events.append(f"CI passing again on {repo} {branch} ({name})")
        return events, now

    def _dependabot(self, repo, seen):
        prs = self._gh(
            "pr", "list", "-R", repo, "--author", "app/dependabot", "--state", "open",
            "--json", "number,title,url",
        )  # fmt: skip
        new = [p for p in prs if p["number"] not in seen]
        events = []
        if new:
            first = new[0]
            more = f" (+{len(new) - 1} more)" if len(new) > 1 else ""
            events.append(f"Dependabot on {repo}: {first['title']}{more}: {first['url']}")
        return events, sorted(p["number"] for p in prs)  # closed numbers never come back

    def _comments(self, repo, me, seen):
        prs = self._gh(
            "pr", "list", "-R", repo, "--author", me, "--state", "open",
            "--json", "number,title,url,comments,reviews",
        )  # fmt: skip
        events, now = [], {}
        for p in prs:
            key = str(p["number"])
            notes = [
                (c.get("createdAt") or "", c.get("author", {}).get("login"), "commented")
                for c in p.get("comments") or []
            ] + [
                (r.get("submittedAt") or "", r.get("author", {}).get("login"), "reviewed")
                for r in p.get("reviews") or []
            ]
            last = seen.get(key, "")  # newest note already told; "" for a PR new since then
            now[key] = max([n[0] for n in notes] + [last])
            fresh = [n for n in notes if n[0] > last and n[1] != me and not _is_bot(n[1])]
            if fresh:
                who = ", ".join(sorted({f"{n[1]} {n[2]}" for n in fresh}))
                events.append(f"{who} on {repo}#{p['number']} {p['title']}: {p['url']}")
        return events, now

    def check(self):
        """(events, errors) since the last check; saves what was seen."""
        state = self._state()
        me = self._gh("api", "user")["login"]
        events, errors = [], []
        for repo, branch in self.active_repos(me):
            prev = state["repos"].get(repo)
            seen = prev or {"ci": {}, "dependabot": [], "comments": {}}
            try:
                ci, seen_ci = self._ci(repo, branch, seen["ci"])
                dep, seen_dep = self._dependabot(repo, seen["dependabot"])
                com, seen_com = self._comments(repo, me, seen["comments"])
            except (OSError, subprocess.SubprocessError, ValueError, KeyError) as e:
                errors.append(f"{repo}: {getattr(e, 'stderr', '') or e}".strip())
                continue
            state["repos"][repo] = {"ci": seen_ci, "dependabot": seen_dep, "comments": seen_com}
            if prev is not None:  # first sight of a repo only records it
                events += ci + dep + com
        self.path.write_text(json.dumps(state, indent=2) + "\n")
        return events, errors


def message_for(events):
    if len(events) == 1:
        return f"{PREFIX} {events[0]}"
    lines = [f"- {e}" for e in events[:MAX_LINES]]
    if len(events) > MAX_LINES:
        lines.append(f"- and {len(events) - MAX_LINES} more")
    return f"{PREFIX} GitHub, {len(events)} updates:\n" + "\n".join(lines)


def notify(store, to, send, repos=None, quiet_hours=None, run=subprocess.run, now=None):
    """Check GitHub and text PJ once if anything is new. Never raises: problems go to the
    journal. Returns the events texted."""
    local = now.astimezone() if now else None
    if quiet(quiet_hours, local):
        return []
    try:
        events, errors = Watch(store, repos, run, now).check()
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as e:
        store.journal(f"GitHub check failed: {getattr(e, 'stderr', '') or e}".strip())
        return []
    for err in errors:
        store.journal(f"GitHub check failed for {err}")
    if not events:
        return []
    try:
        send(to, message_for(events))
    except (OSError, subprocess.SubprocessError) as e:
        store.journal(f"could not text PJ about GitHub: {getattr(e, 'stderr', '') or e}")
        return []
    store.journal(f"texted PJ about GitHub: {len(events)} update(s)")
    return events
