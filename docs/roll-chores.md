# Roll's repo chores: Dependabot PRs

```bash
lab roll chores -C ~/data-engineering                   # dry run: what would merge, what holds
lab roll chores -C ~/data-engineering --apply --admin   # merge what Claude approves, queue the rest
lab roll chores --all --apply [--text]                  # every repo in ROLL_CHORES_REPOS
lab roll scorecard                                      # Roll against Claude and PJ, by tier
```

In Roll's Telegram chat: `/chores` runs `--all --apply` and texts the summary (merges and
holds per repo); `/chores dry` shows what would merge. One run at a time.

`ROLL_CHORES_REPOS` in `.env` lists the checkouts, comma-separated; `:admin` on a repo
makes its merges go past a required review, the standing form of `--admin` below:

```bash
ROLL_CHORES_REPOS=~/data-engineering:admin,~/light-labs
```

`just roll-chores-install` adds a LaunchAgent that runs `--all --apply --text` at 17:30
every day (after work hours, so Roll's local answer is recorded too).

Roll has no merge rights. She answers; Claude ("big brother", `claude -p` on PJ's
subscription) decides; code guards both.

| Step | Who | What |
|---|---|---|
| Answer | Roll, local (`ROLL_CHORES_BRAIN`, default `ollama:llama3.1:8b`) | "Safe to merge with no human review?" yes/no by token probability. Recorded, never acted on. Skipped while a fight runs. |
| Guard | code | Dependabot author, CI green, mergeable, and main has not changed the PR's directory (`.github/` for root PRs) since its head: CI that never ran against current code doesn't count. Otherwise HOLD without calling Claude; a stale PR gets `@dependabot rebase` on `--apply` and is decided again at its new head. CI still running or mergeability `UNKNOWN` (GitHub recomputes it after every push to main) is not a decision: the PR shows `later`, nothing is recorded, and the next run decides. |
| Decide | Claude, cheapest first | Every review starts at haiku and climbs `ROLL_CHORES_LADDER` (default `haiku,sonnet,opus`) only while it isn't settled; see below. Haiku reads the PR only; the rungs above get read-only Read/Grep/Glob in the repo. Each rung answers MERGE, HOLD or ESCALATE, and critiques Roll's answer. |
| Merge | code, `--apply` only | `gh pr merge --squash --match-head-commit <reviewed sha>`, plus `--admin` when the run passes it; the squash body says who decided. At most one merge per directory per run (lock files conflict; Dependabot rebases the rest) and 10 in 24 hours across repos. Past the cap a PR is `later`, checked before Roll or Claude is asked, and nothing is recorded. |

## The ladder

Code sets a tier from the bump: patch of lock files only; minor; major (0.x minor counts,
and so do files beyond lock files). Notes that mention a breaking change, deprecation or
removal go one tier up. The tier no longer picks the model; it sets the floor, the lowest
rung whose MERGE stands alone (patch: haiku, minor: sonnet, major: opus).

| A rung answers | What happens |
|---|---|
| MERGE at or above the floor | merged |
| MERGE below the floor | the next rung is asked; if it says MERGE too, merged (a major bump two cheaper models agree on never reaches opus) |
| HOLD | final, except from the bottom rung, whose HOLD is checked by the next one before it costs PJ's time |
| ESCALATE, no verdict, or a failed call | the next rung is asked; from the top rung it is a HOLD for PJ |

Rungs don't see each other's answers. Every rung asked is recorded on the queue item
(`ladder`: model, verdict, question, why, critique of Roll, seconds, cost), and
`big_brother` is the rung that decided.

A repo that requires a human review (data-engineering) refuses the merge unless the run
passes `--admin`, which uses PJ's repo-admin bypass: Claude's review stands in for PJ's.
Opt in per run, per repo. Required checks have no bypass, so CI must still pass.

## Holds: a dialogue until the merge

After a run with `--apply` (from `/chores` or the schedule), Roll texts each new hold once,
with buttons (`light_labs/agents/roll/holds.py`):

| Button | What happens |
|---|---|
| Fix it | Claude works the hold in a throwaway worktree of the PR's branch, with Read, Grep, Glob, Edit and Write and no shell. `ROLL_FIX_LADDER` (default `sonnet,opus`), cheapest first. Code commits and pushes what it changed, then waits for CI. Green: Roll texts the fix with a Merge button. Red, or the model is stuck: the next rung tries, up to 3 automatic attempts per PR. |
| Merge | Shown only while CI is green. Squash-merges the head PJ was shown (`--match-head-commit`), with `--admin` for repos marked `:admin`. |
| Leave | No more texts for this hold; it stays in the queue. |

Replying to a hold's message is the next turn: PJ's words go to Claude with everything said
so far, and the answer (and any fix) comes back with the buttons. A fix PJ steered that
ends red waits for him and does not climb.

When the ladder is spent Roll offers `ROLL_FIX_TOP` (default `claude-fable-5-2`), called
only on PJ's tap, and suggests opening Heeler to finish the PR with Auto. Caps: 3
automatic attempts per PR, 5 Claude turns in 24 hours across PRs.

Guards, all in code:

- A fix that touches `.github/` is not pushed. The prompt also forbids weakening tests or
  lint rules; CI and PJ's tap are what check that.
- A PR with a fix merges only on PJ's tap. The queue item moves to the pushed head, and a
  chores run holds any PR with a commit Dependabot didn't write without asking Claude.
- Pushing to a Dependabot branch stops Dependabot rebasing it.

Each turn is recorded in the item's `dialogue`: who (PJ or the model), FIXED / ANSWER /
STUCK, the text, files changed, the commit, seconds and cost. A hold PJ merges untouched
is a `merge` label for the `dependabot-merge` stage, as before; one that needed a fix
keeps its `hold` label.

## The record

Each decision is a queue item in `var/roll/queue/` (kind `dependabot`): Roll's answer and
probability, Claude's model, verdict, reason and critique, and the PR facts. Holds stay
pending; when PJ merges or closes the PR, the next run records that in `reason`. A rebase
re-decides the PR.

`lab roll scorecard` per tier: agreement with Claude, false yeses (Roll said merge, Claude
held: the costly mistake), holds PJ merged anyway (Claude too cautious), Claude calls made
and which rung settled each review. A tier that haiku settles almost every time is the
next one for Roll to earn; one that keeps climbing shows what the cheap rungs can't see.

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
