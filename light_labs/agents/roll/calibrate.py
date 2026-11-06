"""Shadow pairs for Roll's writer questions: one brain on merged PRs outside the eval fixtures.

Each PR's raw yes-probability on a question, against the type its title gives ("chore" is
the label for `deps`), lands in var/roll/pairs/deps.jsonl; core/calibrate.py fits the map
the writer applies. The commit-message fixtures are refused here, so the fight still
measures generalisation.

    uv run --group analytics python -m light_labs.agents.roll.calibrate \\
        ollama:llama3.1:8b data-engineering:84 scouter:17 ...
"""

import json
import re
import subprocess
import sys
from datetime import UTC, datetime

from light_labs import config
from light_labs.agents.roll import NUM_CTX
from light_labs.agents.roll.writer import DEPS
from light_labs.core.brain import brain_for
from light_labs.core.decide import ask
from light_labs.evals.commit_message import excerpt, gh, prompt

FIXTURES = config.REPO / "evals/stages/commit-message.yaml"
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
    """One pair per PR and question, printed as it goes."""
    import yaml

    fixture_ids = {f["id"] for f in yaml.safe_load(FIXTURES.read_text())["fixtures"]}
    brain = brain_for(spec, source="roll/calibrate")
    at = datetime.now(UTC).isoformat(timespec="seconds")
    pairs = []
    for repo, pr in prs:
        if f"{repo.replace('-', '_')}_{pr}" in fixture_ids:
            sys.exit(f"{repo}:{pr} is an eval fixture; calibrate on other PRs")
        kind, inp = pr_input(repo, pr)
        text = prompt(inp)
        for q, question in QUESTIONS.items():
            p = ask(brain, text, question, num_ctx=NUM_CTX).p()  # raw: no key, no map
            pairs.append({"robot": "roll", "question": q, "brain": spec, "p": round(p, 4),
                          "label": kind == "chore", "source_id": f"{repo}:{pr}",
                          "label_by": "pr-title", "at": at})  # fmt: skip
            print(f"{repo}:{pr:<5} {kind:6} {q} {p:.2f}")
    return pairs


def write_pairs(spec, pairs):
    """Replace this brain's pairs in var/roll/pairs/deps.jsonl."""
    path = config.VAR / "roll" / "pairs" / "deps.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    keep = [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []
    rows = [p for p in keep if p["brain"] != spec] + pairs
    path.write_text("".join(json.dumps(p) + "\n" for p in rows))
    return path


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        sys.exit(__doc__)
    spec, prs = args[0], [(a.split(":")[0], int(a.split(":")[1])) for a in args[1:]]
    try:
        pairs = calibrate(spec, prs)
    except subprocess.CalledProcessError as e:
        sys.exit(f"gh failed: {e.stderr}")
    print(f"{len(pairs)} pairs -> {write_pairs(spec, pairs)}; `lab calibration ingest` or "
          "Dagster's queue job fits the map")  # fmt: skip


if __name__ == "__main__":
    main()
