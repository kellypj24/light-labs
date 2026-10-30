"""Typed decisions from a model: a question with fixed answers, scored rather than written.

The first layer of a robot's pipeline (Roll's commit type, later Rush's escalate/reply).
A local brain answers from the first token's probabilities at temperature 0
(`Brain.choose`), so the answer is repeatable and carries a confidence. The robot's code
combines several narrow answers into the decision; the model never writes the decision.
Brains without probabilities (Bass via `claude -p`, test doubles) answer in text, parsed
to one choice with confidence 1.

Put the shared input first and the question last: Ollama reuses the cached prompt prefix,
so several questions about one diff cost about one prompt.
"""

import re
from dataclasses import dataclass

YES_NO = ("yes", "no")


@dataclass(frozen=True)
class Answer:
    choice: str
    confidence: float
    probs: dict
    raw: dict = None  # before calibration; the probs a shadow pair records

    def p(self, choice="yes"):
        return self.probs.get(choice, 0.0)


def ask(brain, state, question, choices=YES_NO, num_ctx=None, key=None):
    """One question about `state`, answered with exactly one of `choices`. With `key` (the
    question's calibration name) a yes/no answer from a local brain goes through that
    brain's fitted map, if there is one (core/calibrate.py); `raw` keeps the model's own."""
    system = (
        "Read the input, then answer the question about it with exactly one word: "
        + " or ".join(choices)
        + "."
    )
    user = f"{state}\n\nQuestion: {question}"
    if hasattr(brain, "choose"):
        probs = brain.choose(system, user, choices, num_ctx=num_ctx)
    else:
        text = brain.think(system, user, temperature=0, num_ctx=num_ctx).lower()
        found = next((w for w in re.findall(r"[a-z]+", text) if w in choices), None)
        probs = {c: float(c == found) for c in choices} if found else None
        probs = probs or {c: 1 / len(choices) for c in choices}
    raw = probs
    if key and choices == YES_NO and hasattr(brain, "choose") and getattr(brain, "model", None):
        from light_labs.core import calibrate

        m = calibrate.lookup(f"ollama:{brain.model}", key)
        if m:
            yes = calibrate.apply(m, probs["yes"])
            probs = {"yes": yes, "no": 1 - yes}
    choice = max(choices, key=lambda c: probs[c])
    return Answer(choice, probs[choice], probs, raw)
