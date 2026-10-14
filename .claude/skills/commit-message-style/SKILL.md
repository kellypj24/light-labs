---
name: commit-message-style
description: How a robot writes one commit message from a diff, in PJ's conventional-commit style.
audience: [robots]
load: always
---

Write one commit message for the diff. Output only the message: no preamble, no code
fences, no quotes.

Line 1, the subject. The type, an optional scope in parentheses, a colon, the summary:

    fix(parser): skip blank header lines

- type: feat (new capability), fix (a bug), docs (only docs), ci (only CI or hooks),
  refactor (same behaviour, new shape), test (only tests), chore (deps, cleanup), build.
- summary: imperative ("add", not "added"), lowercase start, no final period, the whole
  line 72 characters or fewer.

Line 2 is blank. Then the body: 1 to 4 short lines or `-` bullets saying what changed and
why. Name the modules, commands or files the diff touches.

Never:
- a PR or issue number, or a link, unless the diff contains it
- a file name that is not in the diff
- a Co-Authored-By or Signed-off-by line (added later)
- filler: robust, seamless, leverage, crucial, delve, holistic
