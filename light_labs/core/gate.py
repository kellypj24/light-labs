"""The sensitivity gate: every call to a `claude:` brain passes here before it leaves.

docs/system-1-system-2.md (Enforcement), docs/plans/decision-framework.md step 1. Fixed
rules, no model. Each caller names its source; SOURCES says what that source carries, and
content checks run on top. Every verdict is recorded (source, rules hit, no payload) in
var/gate/verdicts.jsonl.

Rollout (PJ, 2026-10-30): `client-repo` denies from day one; every other rule records
what it would do and lets the call through. A rule enforces once it is in ENFORCED.
"""

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from light_labs import config
from light_labs.core.sanitize import PERSONAL

CLIENT_REPOS = ("recoup", "dentasys-modernization")
# Repos a Claude call may read with tools (Read, Grep, Glob).
TOOL_REPOS = ("light-labs", "data-engineering", "scouter", "claude-toolkit", "temporal-echoes")
# Unreleased ideas: paths a tool call is denied in an allowed repo, per repo.
UNRELEASED = {repo: ("docs/plans/**", "STATUS.md") for repo in TOOL_REPOS}

# What each source carries, as its caller hands it over. "evals/<stage>" is synthetic.
SOURCES = {
    "rush/auto": {"memory", "board"},
    "rush/auto-handoff": {"board"},
    "rush/mail-teacher": {"mail"},
    "rush/mail-fixtures": {"mail"},
    "roll/keep": {"mail"},
    "roll/keep-teacher": set(),  # sanitized view, personal mail skipped
    "roll/keep-fixtures": set(),
    "roll/chores": set(),
    "roll/calibrate": set(),
    "evals": set(),
}

ENFORCED = {"client-repo"}

CLIENT_TEXT = re.compile(
    r"(?:~|/Users/[^/\s]+)/(?:" + "|".join(CLIENT_REPOS) + r")\b"
    r"|kellypj24/(?:" + "|".join(CLIENT_REPOS) + r")\b"
)
PERSONAL_ADDRESS = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")


class Denied(RuntimeError):
    pass


@dataclass
class Verdict:
    source: str
    hits: dict = field(default_factory=dict)  # rule -> action it asks for
    disallowed: tuple = ()  # --disallowedTools patterns, enforced rules only

    @property
    def action(self):
        for a in ("deny", "sanitize"):
            if a in self.hits.values():
                return a
        return "allow"

    @property
    def blocked(self):
        return any(a == "deny" and r in ENFORCED for r, a in self.hits.items())


def carries(source):
    kind = "evals" if source.startswith("evals/") else source
    if kind not in SOURCES:
        raise ValueError(f"unknown gate source {source!r}; add it to gate.SOURCES")
    return SOURCES[kind]


def repo_name(cwd):
    """The repo a tool call runs in: the lab itself (checkout or deployed release), else
    the git top level's name, else the directory's."""
    path = Path(cwd).resolve()
    if path == config.REPO.resolve() or config.REPO.resolve() in path.parents:
        return "light-labs"
    top = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    return Path(top.stdout.strip()).name if top.returncode == 0 else path.name


def evaluate(source, text, tools="", cwd=None):
    """The rules hit by one call, without recording or raising."""
    v = Verdict(source)
    tags = carries(source)
    repo = repo_name(cwd) if cwd else None
    if repo in CLIENT_REPOS or CLIENT_TEXT.search(text):
        v.hits["client-repo"] = "deny"
    if "memory" in tags:
        v.hits["memory"] = "deny"
    personal = any(PERSONAL.fullmatch(d.lower()) for d in PERSONAL_ADDRESS.findall(text))
    if "mail" in tags or personal:
        v.hits["personal-mail"] = "sanitize"
    if tools and repo not in TOOL_REPOS:
        v.hits["tool-repo"] = "deny"
    elif tools and UNRELEASED.get(repo):
        v.hits["unreleased"] = "sanitize"
        if "unreleased" in ENFORCED:
            # Claude Code applies Read rules to Grep and Glob too.
            v.disallowed = tuple(f"Read(./{p})" for p in UNRELEASED[repo])
    return v


def check(source, system, user, tools="", cwd=None):
    """Evaluate, record, and raise Denied when an enforced rule denies the call."""
    v = evaluate(source, f"{system}\n{user}", tools, cwd)
    record(v, tools, cwd)
    if v.blocked:
        rules = ", ".join(r for r in v.hits if r in ENFORCED)
        raise Denied(f"gate: {source} denied by {rules}")
    return v


def record(v, tools, cwd):
    log = config.VAR / "gate" / "verdicts.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": v.source,
        "action": v.action,
        "blocked": v.blocked,
        "hits": v.hits,
        "enforced": sorted(ENFORCED & v.hits.keys()),
        "tools": tools or None,
        "repo": repo_name(cwd) if cwd else None,
    }
    with log.open("a") as f:
        f.write(json.dumps(row) + "\n")
