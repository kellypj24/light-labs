# Boss fights

Each task class is a stage. A stage has fixtures (inputs plus what a good output must do) and
a scorer. Run the same fixtures through each candidate model and record score, latency and
cost. When a local model clears the bar, the robot gets the weapon: `dln.json` `weapons`
gains the task class and routing sends that work local.

## Stages

| Stage | Robot | Status |
|---|---|---|
| `reply-draft` | Rush | Stub. Fixtures to come from real Agent Net messages and the drafts PJ approved or rejected. |

## Plan for `reply-draft`

- Fixtures: inbox messages and task comments, plus the memory.md snapshot at the time.
- Checks (deterministic first): no invented past work, no "Draft"/sign-off leakage, length,
  escalates when real work is requested, does not promise undecided work.
- Judge pass second, with a pinned rubric; human labels from approve/reject as ground truth.
- Candidates: llama3.1:8b, a Qwen3 8B/14B, a friend's 14B over the tailnet if access is granted,
  and Claude as the ceiling.
- Floor: at least 30 fixtures before reading anything into the numbers.
