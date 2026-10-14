"""commit-message stage: Roll writes a commit message for a real merged PR's diff.

Fixtures are built from PJ's public repos by `build` (below): the PR's file list, a capped
diff excerpt, and the squash commit's message as the reference. Scoring is deterministic
(flags here, the rest in the stage YAML); the mock contestant answers with the reference,
so a mock run proves every reference passes every check.

    uv run python -m light_labs.evals.commit_message build light-labs:22 scouter:17 ...
"""

import json
import re
import subprocess
import sys

TYPES = ("feat", "fix", "docs", "ci", "refactor", "test", "chore", "build", "perf")
SUBJECT = re.compile(rf"^({'|'.join(TYPES)})(\([\w./-]+\))?!?: \S.*$")
MAX_SUBJECT = 72
LOCKS = re.compile(r"(^|/)(uv\.lock|poetry\.lock|package-lock\.json|.*\.lock)$")
FILE_TOKEN = re.compile(
    r"(?<![\w/.-])([\w-]+(?:/[\w.-]+)*\.(?:py|go|sql|ya?ml|md|toml|json|sh|plist|tf|txt|cfg|"
    r"ini|js|ts|lock))\b"
)
PR_REF = re.compile(r"(?<![\w&])#\d+\b")
URL = re.compile(r"https?://\S+")
TRAILER = re.compile(r"^(co-authored-by|signed-off-by):", re.IGNORECASE | re.MULTILINE)
_FENCED = re.compile(r"^```[\w-]*\n(.*?)\n```$", re.DOTALL)

DIFF_BUDGET = 6000  # characters of diff shown; keeps the prompt well inside 8k tokens
LINES_PER_FILE = 40


# --- the prompt -------------------------------------------------------------------------


def prompt(inp):
    files = "\n".join(f"  {f['path']}  +{f['additions']} -{f['deletions']}" for f in inp["files"])
    return (
        f"Repository: {inp['repo']}\n\nFiles changed ({len(inp['files'])}):\n{files}\n\n"
        f"Diff excerpt:\n<diff>\n{inp['diff']}\n</diff>\n\n"
        "Write the commit message for this change."
    )


def clean(text):
    """The message without a fence wrapped around all of it."""
    text = text.strip()
    match = _FENCED.match(text)
    return (match.group(1) if match else text).strip()


# --- scoring flags ----------------------------------------------------------------------


def flags(message, inp):
    """({flag: passed}, one line of notes on the failures)."""
    lines = message.splitlines()
    subject = lines[0].strip() if lines else ""
    kind = subject.split(":", 1)[0].split("(", 1)[0].rstrip("!")
    body = [line for line in lines[2:] if line.strip()] if len(lines) > 2 else []
    paths = [f["path"] for f in inp["files"]]
    known = " ".join(paths) + "\n" + inp["diff"]
    names = {p.rsplit("/", 1)[-1] for p in paths}

    unknown = sorted({t for t in FILE_TOKEN.findall(message) if t not in known and t not in names})
    refs = sorted({r for r in PR_REF.findall(message) if r not in inp["diff"]})
    urls = sorted({u for u in URL.findall(message) if u.rstrip(".,)") not in inp["diff"]})
    result = {
        "subject_format": bool(SUBJECT.match(subject)) and not subject.endswith("."),
        "subject_length": 0 < len(subject) <= MAX_SUBJECT,
        "type_fits": kind in inp["accept_types"],
        "has_body": len(lines) > 2 and not lines[1].strip() and bool(body),
        "no_unknown_files": not unknown,
        "no_invented_refs": not refs and not urls,
        "no_trailers": not TRAILER.search(message),
    }
    notes = {
        "subject_format": f"subject: {subject!r}",
        "subject_length": f"{len(subject)} chars",
        "type_fits": f"{kind!r} not in {inp['accept_types']}",
        "has_body": "no blank line + body after the subject",
        "no_unknown_files": f"not in the diff: {unknown}",
        "no_invented_refs": f"refs {refs} urls {urls}",
        "no_trailers": "has a trailer line",
    }
    return result, "; ".join(f"{k}: {v}" for k, v in notes.items() if not result[k])


def run_sample(brain, inp):
    from light_labs.agents import roll
    from light_labs.agents.roll import writer
    from light_labs.core.brain import Mock

    if isinstance(brain, Mock):  # the oracle: proves every reference passes every check
        raw, how = inp["reference"], "oracle"
    else:
        user = prompt(inp)
        paths = [f["path"] for f in inp["files"]]
        kind, how = writer.classify(brain, paths, user, num_ctx=roll.NUM_CTX)
        raw = writer.write(
            brain, roll.system_prompt(user), user, kind, roll.TEMPERATURE, roll.NUM_CTX
        )
    message = clean(raw)
    result, notes = flags(message, inp)
    notes = f"type by {how}; {notes}" if notes else ""
    return {"raw": raw, "draft": message, "flags": result, "notes": notes}


# --- building fixtures from merged PRs --------------------------------------------------


def excerpt(diff):
    """Per-file hunks capped at LINES_PER_FILE, lock files omitted, DIFF_BUDGET overall."""
    chunks = re.split(r"(?m)^(?=diff --git )", diff)
    out, used, skipped = [], 0, 0
    for chunk in chunks:
        if not chunk.strip():
            continue
        path = re.search(r"^diff --git a/(\S+)", chunk, re.MULTILINE)
        if path and LOCKS.search(path.group(1)):
            text = f"diff --git a/{path.group(1)} (lock file; diff omitted)\n"
        else:
            lines = chunk.splitlines()
            text = "\n".join(lines[:LINES_PER_FILE])
            if len(lines) > LINES_PER_FILE:
                text += f"\n[... {len(lines) - LINES_PER_FILE} more lines]"
            text += "\n"
        if used + len(text) > DIFF_BUDGET:
            skipped += 1
            continue
        out.append(text)
        used += len(text)
    if skipped:
        out.append(f"[{skipped} more file(s) not shown]\n")
    return "".join(out).rstrip()


def reference(message):
    """The squash commit's message as a commit message: no trailing (#N) on the subject, no
    trailers, session links or attribution, and a PR body's test plan cut."""
    lines = message.strip().splitlines()
    subject = re.sub(r"(\s*\(#\d+\))+$", "", lines[0]).strip()
    body = []
    for line in lines[1:]:
        if line.strip().lower() == "## test plan":
            break
        if TRAILER.match(line) or "Generated with [Claude Code]" in line:
            continue
        if "claude.ai/code/session" in line or line.strip().lower() == "## summary":
            continue
        body.append(line.rstrip())
    text = "\n".join(body).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return f"{subject}\n\n{text}" if text else subject


def accept_types(kind, paths):
    """The reference's type, plus the neighbours a fair reviewer would also accept."""
    neighbours = {
        # fix and feat: a change that corrects behaviour by adding code reads as either, and
        # Bass misses the line too; a reviewer relabels it in seconds.
        "feat": ["fix"],
        "fix": ["feat"],
        "refactor": ["chore"],
        "chore": ["build", "refactor", "ci"],
        "ci": ["build", "chore"],
        "build": ["chore", "ci"],
        "test": ["chore"],
    }
    out = [kind, *neighbours.get(kind, [])]
    if all(p.endswith(".md") for p in paths):
        out.append("docs")
    return sorted(set(out))


# Too generic to show the message is about this diff.
GENERIC = {"readme", "__init__", "skill", "claude", "main", "docs", "scripts", "fixtures",
           "core", "utils", "src", "tests", "workflows", "resources", "jobs", "models"}  # fmt: skip


def mentions(paths):
    """Names a message should touch (any one of them): stems of the non-test, non-lock
    files changed and their directories; `ci` for a CI workflow."""
    terms = set()
    for p in paths:
        if LOCKS.search(p) or "/tests/" in f"/{p}" or p.split("/")[-1].startswith("test_"):
            continue
        if p.startswith(".github/workflows/"):
            terms.add("ci")
        name = p.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
        parent = p.rsplit("/", 2)[-2].lower() if "/" in p else ""
        for term in (name, name.replace("_", " "), parent):
            if len(term) >= 4 and term not in GENERIC and not term.startswith("."):
                terms.add(term)
    return sorted(terms)


def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def build_fixture(repo, pr, owner="kellypj24"):
    full = f"{owner}/{repo}"
    view = json.loads(gh("pr", "view", str(pr), "-R", full, "--json", "files,mergeCommit"))
    message = json.loads(gh("api", f"repos/{full}/commits/{view['mergeCommit']['oid']}"))["commit"][
        "message"
    ]
    ref = reference(message)
    kind = SUBJECT.match(ref.splitlines()[0])
    if not kind:
        raise ValueError(f"{repo}#{pr}: subject is not conventional: {ref.splitlines()[0]!r}")
    files = [
        {"path": f["path"], "additions": f["additions"], "deletions": f["deletions"]}
        for f in view["files"]
    ]
    paths = [f["path"] for f in files]
    fixture = {
        "id": f"{repo.replace('-', '_')}_{pr}",
        "category": kind.group(1),
        "input": {
            "repo": repo,
            "files": files,
            "diff": excerpt(gh("pr", "diff", str(pr), "-R", full)),
            "reference": ref,
            "accept_types": accept_types(kind.group(1), paths),
        },
    }
    terms = mentions(paths)
    if terms:
        fixture["expect"] = {"contains_any": terms}
    return fixture


def main(argv=None):
    import yaml

    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] != "build":
        sys.exit(__doc__)
    fixtures = []
    for spec in args[1:]:
        repo, pr = spec.split(":")
        try:
            fixtures.append(build_fixture(repo, int(pr)))
        except (ValueError, subprocess.CalledProcessError) as e:
            print(f"skip {spec}: {e}", file=sys.stderr)
    yaml.safe_dump(fixtures, sys.stdout, sort_keys=False, allow_unicode=True, width=100)


if __name__ == "__main__":
    main()
