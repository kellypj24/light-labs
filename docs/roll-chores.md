# Roll's repo chores: Dependabot PRs

```bash
lab roll chores -C ~/data-engineering                   # dry run: what would merge, what holds
lab roll chores -C ~/data-engineering --apply --admin   # merge what Claude approves, queue the rest
lab roll scorecard                                      # Roll against Claude and PJ, by tier
```

Roll has no merge rights. She answers; Claude ("big brother", `claude -p` on PJ's
subscription) decides; code guards both.

| Step | Who | What |
|---|---|---|
| Answer | Roll, local (`ROLL_CHORES_BRAIN`, default `ollama:llama3.1:8b`) | "Safe to merge with no human review?" yes/no by token probability. Recorded, never acted on. Skipped while a fight runs. |
| Guard | code | Dependabot author, CI green, mergeable. Otherwise HOLD without calling Claude. |
| Decide | Claude, tier by size | patch of lock files only: haiku. Minor: sonnet. Major (0.x minor counts), or files beyond lock files: opus. Notes that mention a breaking change, deprecation or removal: one tier up. Sonnet and opus get read-only Read/Grep/Glob in the repo. Answers MERGE or HOLD, and critiques Roll's answer. |
| Merge | code, `--apply` only | `gh pr merge --squash --match-head-commit <reviewed sha>`, plus `--admin` when the run passes it; the squash body says who decided. At most one merge per directory per run (lock files conflict; Dependabot rebases the rest) and 10 a day. |

A repo that requires a human review (data-engineering) refuses the merge unless the run
passes `--admin`, which uses PJ's repo-admin bypass: Claude's review stands in for PJ's.
Opt in per run, per repo. Required checks have no bypass, so CI must still pass.

## The record

Each decision is a queue item in `var/roll/queue/` (kind `dependabot`): Roll's answer and
probability, Claude's model, verdict, reason and critique, and the PR facts. Holds stay
pending; when PJ merges or closes the PR, the next run records that in `reason`. A rebase
re-decides the PR.

`lab roll scorecard` per tier: agreement with Claude, false yeses (Roll said merge, Claude
held: the costly mistake) and holds PJ merged anyway (Claude too cautious).

## The weapon

```bash
lab roll chores-fixtures                              # append new Claude-reviewed PRs
just eval dependabot-merge mega-man,proto-14b,bass 3  # the fight (ask PJ first)
```

`evals/stages/dependabot-merge.yaml` holds one fixture per Claude-reviewed PR, its latest
review: the record's facts plus the PR's notes, refetched (Dependabot PRs in public repos
are public, so no rewrite). Label `merge` / `hold` is Claude's verdict, or `merge` when PJ
merged a hold himself; a close carries no label (Dependabot closes what it supersedes).
PRs code held never reached Claude and make no fixture. The stage scores the same
`chores.answer` call a run records.

A wrong answer merges without review, so the bar is 0.95 and zero false yeses (PJ
2026-10-29), earned per tier, patch first; an earned tier stops calling Claude.
