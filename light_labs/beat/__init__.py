"""Beat: the lab's Dagster code location (`just beat`).

Orchestrates the data flow that `just analytics` runs by hand: land the runner's files and
the robots' queues in var/lab.duckdb (raw.*), then `dbt build` the analytics project. The
sensors run it when a fight finishes or a queue changes, and never while a fight is on.

Fights stay out of Beat: they are heavy, and PJ starts them.
"""

from dagster import Definitions

from light_labs.beat.assets import ALL_ASSETS, DBT
from light_labs.beat.jobs import ALL_JOBS
from light_labs.beat.sensors import ALL_SENSORS

defs = Definitions(assets=ALL_ASSETS, jobs=ALL_JOBS, sensors=ALL_SENSORS, resources={"dbt": DBT})
