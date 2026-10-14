"""Roll's commit message pipeline: decide the type, then write. Shared by the robot and the
evals.

The type comes first because a writer asked for both anchors on whatever type its prompt
shows (the first commit-message fight labelled almost everything `fix`). File sets that
can only be one type are decided by rule; the rest by a short call that sees the files
and the diff, answers one word, and has no example to copy.
"""

import re

TYPES = {
    "feat": "adds a capability: a new command, option, model, stage, endpoint or behaviour",
    "fix": "corrects behaviour that was wrong or broken",
    "refactor": "changes code structure or names without changing behaviour",
    "docs": "changes only documentation",
    "ci": "changes only CI workflows, hooks or check configuration",
    "test": "changes only tests",
    "chore": "dependency bumps, lock refreshes, cleanup with no behaviour change",
}

CLASSIFIER = (
    "You label a code change with one conventional-commit type. Answer with the type "
    "only, one word.\n\n"
    + "\n".join(f"{name}: {meaning}" for name, meaning in TYPES.items())
    + "\n\nIf the change adds something new, it is feat, even if it also fixes things."
)

_CI = re.compile(r"^(\.github/|\.pre-commit-config\.yaml$|\.gitleaks\.toml$|\.zizmor)")
_DOC = re.compile(r"(\.md|\.rst)$|(^|/)docs/")
_TEST = re.compile(r"(^|/)tests?/|(^|/)test_[^/]+$|_test\.go$")


def rule_type(paths):
    """The type when the files alone decide it, else None."""
    if paths and all(_DOC.search(p) for p in paths):
        return "docs"
    if paths and all(_CI.search(p) for p in paths):
        return "ci"
    if paths and all(_TEST.search(p) for p in paths):
        return "test"
    return None


def classify(brain, paths, prompt, num_ctx=None):
    """(type, how): by rule when the files decide it, else one short model call."""
    kind = rule_type(paths)
    if kind:
        return kind, "rule"
    raw = brain.think(CLASSIFIER, prompt, temperature=0, num_ctx=num_ctx)
    for word in re.findall(r"[a-z]+", raw.lower()):
        if word in TYPES:
            return word, "model"
    return "chore", "fallback"


def write(brain, system, prompt, kind, temperature=None, num_ctx=None):
    """The message, written with its type fixed."""
    user = (
        f"{prompt}\n\nThe type is `{kind}`. Start the subject with `{kind}:` or "
        f"`{kind}(<scope>):`, keep the whole subject under 60 characters, then a blank line "
        "and a body of 1 to 4 lines saying what changed and why."
    )
    return brain.think(system, user, temperature=temperature, num_ctx=num_ctx)
