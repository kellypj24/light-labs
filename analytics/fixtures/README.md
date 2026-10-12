Synthetic eval results for CI: `just analytics-check` ingests these into a throwaway
DuckDB file and runs `dbt build` over them. They cover a full Mega Man run, a Bass
baseline, a filtered run with a harness error, and an older file without `run_id`.
