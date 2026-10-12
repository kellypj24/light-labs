---
name: lab-workflow
description: How changes land in light-labs. Use before committing, pushing or opening a PR in this repo.
audience: [auto]
---

1. Branch first: never commit to `main`. Name branches `feature/<topic>` or `fix/<topic>`.
   Re-check `git branch --show-current` after any checkout, stash or rebase.
2. Run `just check` (pre-commit hooks + unit tests, identical to CI). Fix failures; never
   use `--no-verify`.
3. Commit with a conventional prefix (`feat:`, `fix:`, `ci:`, `docs:`, `chore:`) and the
   Co-Authored-By trailer.
4. Push with `PREPUSH_ACK=1 git push -u origin HEAD`, only after `just check` passed on the
   current tree, and say which run confirmed it. This repo opted into the ack
   (`git config claude.prepushAck true`).
5. Open the PR with `gh pr create`: `## Summary` (1-3 bullets) and `## Test plan`. Keep
   README and `docs/` in step with the change in the same PR.
6. `main` has a ruleset with no bypass: changes arrive by PR and `CI Success` must pass.
   When PJ asks for the merge and CI is green: `gh pr merge <n> --squash --delete-branch`,
   then `git checkout main && git pull --ff-only`.
7. Never commit `.env`, `var/`, or any `memory.md`; they hold deployment details about
   other people's systems. `scripts/gitleaks.sh` and push protection are the backstop,
   not the plan.
