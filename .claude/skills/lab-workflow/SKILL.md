---
name: lab-workflow
description: How changes land in light-labs (and PJ's other repos) with `lab git`. Use before committing, pushing, opening or merging a PR, or cleaning up branches.
audience: [auto]
---

1. Branch first: never commit to `main`. Name branches `feature/<topic>` or `fix/<topic>`.
   Re-check `git branch --show-current` after any checkout, stash or rebase.
2. Ship with `lab git ship -F <msg-file> [--body-file <pr-body>]`: it runs `just check`,
   and only if that passes commits everything, pushes and opens (or finds) the PR. Its
   output is the summary; don't re-run `git status`/`git log`/`gh pr view` after it. Never
   use `--no-verify`. The message: conventional prefix (`feat:`, `fix:`, `ci:`, `docs:`,
   `chore:`) and the Co-Authored-By trailer. The PR body: `## Summary` (1-3 bullets),
   `## Test plan`, attribution line. Keep README and `docs/` in step in the same PR.
   Doing it by hand instead: `just check && PREPUSH_ACK=1 git push -u origin HEAD` (this
   repo opted into the ack; gate with `&&`).
3. `main` has a ruleset with no bypass: changes arrive by PR and `CI Success` must pass.
   When PJ asks for the merge: `lab git land <n>`. It waits for CI, merges only on green
   (on red it prints the failing job's log tail), squash-merges on GitHub and deletes the
   branch there. Locally it moves to `main` (detached at `origin/main` when another
   worktree has `main`) and deletes the branch unless another worktree has it open.
4. `lab git status` for the state of the repo and its PRs; `lab git tidy` lists merged or
   abandoned branches and worktrees. `tidy --apply` deletes, so run it only when PJ asks;
   `review` rows are never deleted.
5. `lab git` works in any of PJ's repos (`lab git -C ~/<repo> ...`).
6. Labels come from `.github/labels.toml`: `ship` labels its PR; `lab git label` backfills
   open PRs. `lab git labels --apply` (and `--prune`) changes the repo's label set, so
   only when PJ asks. A new top-level area of the code gets an `[areas.<name>]` entry in
   the same PR.
7. Never commit `.env`, `var/`, or any `memory.md`; they hold deployment details about
   other people's systems. `scripts/gitleaks.sh` and push protection are the backstop,
   not the plan.
