Synthetic eval results for CI: `just analytics-check` ingests these into a throwaway
DuckDB file and runs `dbt build` over them. They cover a full Mega Man run, a Bass
baseline, a filtered run with a harness error, and an older file without `run_id`.

`queue/` mirrors `var/`: one synthetic approval queue (`rush/queue/{sent,rejected,pending}`)
with an unedited send, an edited send, an older item without `drafted`, a rejection with a
reason, and a pending draft.

`*.run.json` and `*.telemetry.jsonl` are run records and heat readings for the two runs: one
completed on AC, one cancelled ("machine hot") on battery after a throttled reading.
