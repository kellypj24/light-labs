"""Calibrate Roll's yes/no questions for one brain on merged PRs outside the eval fixtures.

A question has its own yes-bias per brain, so classify() compares an answer with that
question's baseline: the mean yes-probability across change types, from PRs whose type is
known from their titles. The commit-message fixtures are refused here, so the fight still
measures generalisation.

    uv run --group analytics python -m light_labs.agents.roll.calibrate \\
        ollama:llama3.1:8b data-engineering:84 scouter:17 ...
"""

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from light_labs.agents.roll import NUM_CTX
from light_labs.agents.roll.writer import DEPS
from light_labs.core.brain import brain_for
from light_labs.core.decide import ask
from light_labs.evals.commit_message import excerpt, gh, prompt

CALIBRATION = Path(__file__).resolve().parent / "calibration.json"
FIXTURES = Path(__file__).resolve().parents[3] / "evals/stages/commit-message.yaml"
QUESTIONS = {"deps": DEPS}


def pr_input(repo, pr, owner="kellypj24"):
    """(type from the PR title, the stage's prompt input) for one merged PR."""
    full = f"{owner}/{repo}"
    view = json.loads(gh("pr", "view", str(pr), "-R", full, "--json", "title,files"))
    m = re.match(r"^(\w+)", view["title"])
    files = [
        {"path": f["path"], "additions": f["additions"], "deletions": f["deletions"]}
        for f in view["files"]
    ]
    inp = {"repo": repo, "files": files, "diff": excerpt(gh("pr", "diff", str(pr), "-R", full))}
    return m.group(1), inp


def calibrate(spec, prs):
    import yaml

    fixture_ids = {f["id"] for f in yaml.safe_load(FIXTURES.read_text())["fixtures"]}
    brain = brain_for(spec)
    rows = []
    for repo, pr in prs:
        if f"{repo.replace('-', '_')}_{pr}" in fixture_ids:
            sys.exit(f"{repo}:{pr} is an eval fixture; calibrate on other PRs")
        kind, inp = pr_input(repo, pr)
        text = prompt(inp)
        probs = {q: ask(brain, text, QUESTIONS[q], num_ctx=NUM_CTX).p() for q in QUESTIONS}
        rows.append({"pr": f"{repo}:{pr}", "type": kind, "p": probs})
        print(f"{repo}:{pr:<5} {kind:6} " + " ".join(f"{q} {p:.2f}" for q, p in probs.items()))
    by_type = {}
    for row in rows:
        by_type.setdefault(row["type"], []).append(row["p"])
    # Mean over types of the per-type mean, so the mix of types in the set doesn't move it.
    baselines = {
        q: sum(sum(p[q] for p in ps) / len(ps) for ps in by_type.values()) / len(by_type)
        for q in QUESTIONS
    }
    return {
        "brain": spec,
        "built": datetime.now(UTC).date().isoformat(),
        "baselines": {q: round(b, 4) for q, b in baselines.items()},
        "types": {t: len(ps) for t, ps in sorted(by_type.items())},
        "by_type": {
            t: {q: round(sum(p[q] for p in ps) / len(ps), 4) for q in QUESTIONS}
            for t, ps in sorted(by_type.items())
        },
        "prs": [r["pr"] for r in rows],
    }


def baseline(brain, question):
    """The question's calibrated baseline for this brain; 0 when uncalibrated."""
    spec = f"ollama:{brain.model}"
    return load().get(spec, {}).get("baselines", {}).get(question, 0.0)


def load():
    return json.loads(CALIBRATION.read_text()) if CALIBRATION.exists() else {}


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        sys.exit(__doc__)
    spec, prs = args[0], [(a.split(":")[0], int(a.split(":")[1])) for a in args[1:]]
    try:
        result = calibrate(spec, prs)
    except subprocess.CalledProcessError as e:
        sys.exit(f"gh failed: {e.stderr}")
    data = load()
    data[spec] = result
    CALIBRATION.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
