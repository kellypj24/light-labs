Synthetic eval results for CI: `just analytics-check` ingests these into a throwaway
DuckDB file and runs `dbt build` over them. They cover a full Mega Man run, a Bass
baseline, a filtered run with a harness error, and an older file without `run_id`.

`queue/` mirrors `var/`: one synthetic approval queue (`rush/queue/{sent,rejected,pending}`)
with an unedited send, an edited send, an older item without `drafted`, a rejection with a
reason, and a pending draft.

`claude/projects/` mirrors Claude Code's transcripts: two sessions in two projects, one with
a subagent transcript, an assistant message split over two records, a failed tool call and
a slash-command expansion that is not a typed prompt.

`*.run.json` and `*.telemetry.jsonl` are run records and heat readings for the two runs: one
completed on AC, one cancelled ("machine hot") on battery after a throttled reading.

`calibration/roll/pairs/` mirrors `var/roll/pairs/`: 60 synthetic shadow pairs for one
question and brain, overconfident (raw p 0.55-0.97, about 40% positive), so Platt scaling
fits and beats the raw probability.
