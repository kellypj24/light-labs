"""The repo review queue: what on GitHub needs PJ, across DASH_REPOS.

- his open PRs with failing checks or a review decision against them
- PRs by someone else that ask for his review (Dependabot's are Roll's)
- a red default branch, from the state Rush's GitHub watch already keeps
- open issues assigned to him

Slow (several `gh` calls), so the dashboard runs it on a background thread and shows the
cached answer.
"""

import os

from light_labs.core import mcp_server

OWNER = "kellypj24"
REPOS = (
    "light-labs",
    "claude-toolkit",
    "data-engineering",
    "scouter",
    "recoup",
    "temporal-echoes",
    "dentasys-modernization",
    "pjksystems-site",
)
SEARCH_FIELDS = "repository,number,title,url,author"


def repos():
    raw = os.environ.get("DASH_REPOS", "")
    names = [n.strip() for n in raw.split(",") if n.strip()] or list(REPOS)
    return {n if "/" in n else f"{OWNER}/{n}" for n in names}


def _bot(author):
    login = ((author or {}).get("login") or "").lower()
    return (author or {}).get("is_bot") or login.endswith("[bot]") or "dependabot" in login


def _row(kind, repo, number, title, detail, url=""):
    return {"kind": kind, "repo": repo.rpartition("/")[2], "number": number,
            "title": " ".join(str(title or "").split()), "detail": detail, "url": url}  # fmt: skip


def fetch(run=None, watched=None):
    """Rows for the review queue, most urgent kind first."""
    kw = {"run": run} if run else {}
    watched = repos() if watched is None else watched
    status = mcp_server.github_status(**kw)
    rows = []
    for repo, jobs in sorted(status["ci_failing"].items()):
        if repo in watched:
            rows.append(_row("ci", repo, None, "main is red", ", ".join(jobs)))
    for pr in status["open_prs"]:
        if pr["repo"] not in watched or pr.get("draft"):
            continue
        detail = []
        if pr["checks_failing"]:
            detail.append(f"{pr['checks_failing']} failing")
        if pr.get("review") == "CHANGES_REQUESTED":
            detail.append("changes requested")
        if detail:
            rows.append(
                _row("pr", pr["repo"], pr["number"], pr["title"], ", ".join(detail), pr["url"])
            )
    asked = mcp_server._gh(
        "search", "prs", "--review-requested", "@me", "--state", "open",
        "--json", SEARCH_FIELDS, **kw,
    )  # fmt: skip
    for pr in asked or []:
        repo = (pr.get("repository") or {}).get("nameWithOwner", "")
        if repo in watched and not _bot(pr.get("author")):
            rows.append(
                _row("review", repo, pr["number"], pr["title"], "review requested", pr["url"])
            )
    issues = mcp_server._gh(
        "search", "issues", "--assignee", "@me", "--state", "open",
        "--json", SEARCH_FIELDS, **kw,
    )  # fmt: skip
    for issue in issues or []:
        repo = (issue.get("repository") or {}).get("nameWithOwner", "")
        if repo in watched:
            rows.append(_row("issue", repo, issue["number"], issue["title"], "", issue["url"]))
    return rows
