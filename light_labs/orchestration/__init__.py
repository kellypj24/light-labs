"""The lab's Dagster code location: the only path data takes into var/lab.duckdb.

Land the runner's files and the robots' queues (raw.*), then `dbt build` the analytics
project. `just analytics` executes `analytics_job`; the sensors run the narrower jobs when a
fight finishes or a queue changes, and never while a fight is on (`just dagster` for the UI).

Fights are never orchestrated here: they are heavy, and PJ starts them.
"""

from dagster import Definitions, in_process_executor

from light_labs.orchestration.assets import ALL_ASSETS, DBT
from light_labs.orchestration.jobs import ALL_JOBS
from light_labs.orchestration.sensors import ALL_SENSORS

# Every step writes the same DuckDB file, which allows one writer: run steps one at a time
# in a single process instead of Dagster's default of one process per step.
defs = Definitions(
    assets=ALL_ASSETS,
    jobs=ALL_JOBS,
    sensors=ALL_SENSORS,
    resources={"dbt": DBT},
    executor=in_process_executor,
)
