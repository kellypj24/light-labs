"""Run one eval sample through a robot's real pipeline. Subprocess target of the Go runner.

    python -m light_labs.evals.run_one --input-json '{"stage": ..., "brain": ..., ...}'

Input:  {"stage": "reply-draft", "brain": "ollama:llama3.1:8b", "memory": "<text>",
         "input": {...stage-specific...}}
Output: one JSON object on stdout, always, even on failure:
        {"ok": bool, "result": {...}, "stats": {...}, "error": str}
        result: {"raw", "draft", "escalate"?, "flags"?: {name: bool}, "notes"?}
The Go side scores `result`; this side never judges.
"""

import argparse
import contextlib
import json
import sys
import traceback

from light_labs.core.brain import brain_for


def reply_draft(brain, memory, inp):
    """Rush drafting a reply or task comment: the exact prompts the heartbeat uses."""
    from light_labs.agents import rush
    from light_labs.agents.rush.heartbeat import comment_prompt, draft, reply_prompt

    content = inp["content"]
    if inp.get("kind", "reply") == "comment":
        earlier = [(e["author"], e["text"]) for e in inp.get("earlier", [])]
        user = comment_prompt(rush.NAME, inp.get("title", ""), earlier, inp["sender"], content)
    else:
        user = reply_prompt(rush.NAME, inp["sender"], inp.get("summary"), content)
    system = rush.system_prompt(user, memory_text=memory)
    raw, escalate, body = draft(brain, system, user, content, rush.NAME, rush.TEMPERATURE)
    return {"raw": raw, "draft": body, "escalate": escalate}


def dbt_model(brain, memory, inp):
    """Guts Man writing one dbt model, built beside its reference and compared."""
    from light_labs.evals import dbt_model as stage

    return stage.run_sample(brain, inp)


STAGES = {"reply-draft": reply_draft, "dbt-model": dbt_model}


def run(payload):
    stage = STAGES.get(payload.get("stage"))
    if stage is None:
        raise ValueError(f"unknown stage {payload.get('stage')!r}; known: {', '.join(STAGES)}")
    brain = brain_for(payload["brain"])
    # stdout carries only the envelope; anything a stage's tools print (dbt logs its
    # errors there even with --quiet) goes to stderr.
    with contextlib.redirect_stdout(sys.stderr):
        result = stage(brain, payload.get("memory"), payload["input"])
    return result, brain.last


def main(argv=None):
    parser = argparse.ArgumentParser(prog="run_one")
    parser.add_argument("--input-json", required=True)
    args = parser.parse_args(argv)
    try:
        result, stats = run(json.loads(args.input_json))
        out = {"ok": True, "result": result, "stats": stats, "error": ""}
    except Exception as exc:  # noqa: BLE001 - the envelope must report every failure
        out = {"ok": False, "result": None, "stats": {}, "error": f"{exc}"}
        traceback.print_exc(file=sys.stderr)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
