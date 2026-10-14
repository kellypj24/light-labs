"""Roll's commit message pipeline: decide the type, then write. Shared by the robot and the
evals.

The type comes first because a writer asked for both anchors on whatever type its prompt
shows (the first commit-message fight labelled almost everything `fix`). File sets that
can only be one type are decided by rule; the rest by a short call that sees the files
and the diff and walks ordered yes/no questions. Docs and test are never offered to the
model: with "docs" on the menu it called mixed code-and-docs changes docs.
"""

import re

# Asked in order; the first yes is the type. docs and test are decided by rule only (every
# file docs; every non-doc file a test), since a change that touches code is never only
# docs. ci comes first: asked after feat, "adds a new check" made new workflows feat.
QUESTIONS = {
    "ci": "Does it change only CI workflows, hooks, the scripts they run or check config?",
    "fix": "Was something broken or wrong before, and does this change correct it?",
    "feat": "Does it add something new: a command, option, check, stage, file or behaviour?",
    "refactor": "Does code behave the same afterwards, only restructured or renamed?",
    "chore": "Is it dependency bumps, lock refreshes or cleanup?",
}


def classifier(allowed):
    asks = "\n".join(f"{i}. {QUESTIONS[t]} -> {t}" for i, t in enumerate(allowed, 1))
    return (
        "You label a code change with one conventional-commit type. Go through the "
        "questions in order and answer with the type of the first one whose answer is "
        f"yes. Answer with the type only, one word.\n\n{asks}"
    )


_CI = re.compile(r"^(\.github/|\.pre-commit-config\.yaml$|\.gitleaks\.toml$|\.zizmor|\.sqlfluff$)")
_DOC = re.compile(r"(\.md|\.rst)$|(^|/)docs/")
_TEST = re.compile(r"(^|/)tests?/|(^|/)test_[^/]+$|_test\.go$")


def rule_type(paths):
    """The type when the files alone decide it, else None. Docs ride along: CI changes
    with their docs are still ci, tests with docs still test."""
    if not paths:
        return None
    if all(_DOC.search(p) for p in paths):
        return "docs"
    rest = [p for p in paths if not _DOC.search(p)]
    if all(_CI.search(p) for p in rest):
        return "ci"
    if all(_TEST.search(p) for p in rest):
        return "test"
    return None


def classify(brain, paths, prompt, num_ctx=None):
    """(type, how): by rule when the files decide it, else one short model call."""
    kind = rule_type(paths)
    if kind:
        return kind, "rule"
    allowed = list(QUESTIONS)
    raw = brain.think(classifier(allowed), prompt, temperature=0, num_ctx=num_ctx)
    for word in re.findall(r"[a-z]+", raw.lower()):
        if word in allowed:
            return word, "model"
    return "chore", "fallback"


def write(brain, system, prompt, kind, temperature=None, num_ctx=None):
    """The message, written with its type fixed."""
    user = (
        f"{prompt}\n\nThe type is `{kind}`. Start the subject with `{kind}:` or "
        f"`{kind}(<scope>):`, keep the whole subject under 60 characters, then a blank line "
        "and a body of 1 to 4 lines saying what changed and why. Name the main module or "
        "file the change is in."
    )
    return brain.think(system, user, temperature=temperature, num_ctx=num_ctx)
