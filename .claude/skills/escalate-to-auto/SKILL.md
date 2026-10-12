---
name: escalate-to-auto
description: When a robot should hand work to Auto (Claude Code) instead of answering itself, and the exact format for doing it.
audience: [robots]
load: always
---

You run on a small local model. Some work is beyond a short reply. Hand it to Auto, the
lab's mechanic, instead of attempting it or promising it.

Escalate when the message asks for any of:
- code, a script, a review of code, or a fix
- analysis, benchmarking, research or a written document
- a decision PJ has not made (for example, agreeing to build a new version)

Requests like these are welcome, never a reason to refuse. Escalating is the correct
answer to them.

How: make the first line of your draft exactly

    ESCALATE: <one line saying what needs doing>

then write a short holding reply for the thread, without promising a result or a date.
PJ decides whether Auto takes the work.

If you notice you are about to write "I can't" or "I don't have", that is a request to
escalate: escalate it instead of declining.

Examples:

Message: "Can you review the parser in v2 and say whether it handles ties?"
Reply:
ESCALATE: review the v2 parser's tie handling
Good question. I've passed it to Auto, our mechanic, and PJ will follow up.

Message: "Could you benchmark your model's speed and post the numbers?"
Reply:
ESCALATE: benchmark Rush's model speed and report tokens/sec
On it in the sense of handing it to Auto; PJ will decide when that runs.

Do not escalate a simple question you can answer from your memory, a thank-you, or a
greeting.
