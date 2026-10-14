---
name: commit-message-style
description: How a robot writes one commit message from a diff, in PJ's conventional-commit style.
audience: [robots]
load: always
---

Write one commit message for the diff. Output only the message: no preamble, no code
fences, no quotes.

Line 1, the subject: the type you are given, an optional scope in parentheses, a colon,
then a summary of this diff. Shapes only; never reuse their words:

    feat(cli): add a dry-run flag to sync
    docs: explain the release checklist
    ci: cache the Go module download

The summary is imperative ("add", not "added"), starts lowercase, has no final period,
and the whole line stays under 60 characters.

Line 2 is blank. Then the body: 1 to 4 short lines or `-` bullets saying what changed and
why. Name the modules, commands or files the diff touches.

Never:
- a PR or issue number, or a link, unless the diff contains it
- a file name that is not in the diff
- a Co-Authored-By or Signed-off-by line (added later)
- filler: robust, seamless, leverage, crucial, delve, holistic
