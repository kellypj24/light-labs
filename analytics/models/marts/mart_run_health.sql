{#
    One row per eval run: how it ended, why, and how hard it worked the machine. A run
    still "running" whose last sign of life is older than `run_stale_minutes` was killed
    without a chance to say so: abandoned.
#}

WITH readings AS (

    SELECT
        run_id,
        COUNT(*) AS reading_count,
        MAX(battery_temp_c) AS peak_battery_temp_c,
        AVG(battery_temp_c) AS mean_battery_temp_c,
        MIN(cpu_speed_limit) AS min_cpu_speed_limit,
        COUNT(*) FILTER (WHERE is_throttled) AS throttled_reading_count,
        COUNT(*) FILTER (WHERE NOT is_on_ac) AS on_battery_reading_count,
        MIN(battery_pct) AS min_battery_pct,
        AVG(ollama_cpu) AS mean_ollama_cpu,
        MAX(read_at) AS last_read_at
    FROM {{ ref('stg_eval_telemetry') }}
    GROUP BY run_id

),

joined AS (

    SELECT
        runs.run_id,
        runs.stage,
        runs.contestants,
        runs.status,
        runs.stop_reason,
        runs.started_at,
        runs.ended_at,
        runs.duration_minutes,
        runs.total_samples,
        runs.done_samples,
        runs.passed_samples,
        runs.harness_error_count,
        runs.cool_pause_count,
        runs.cool_seconds,
        runs.git_commit,
        readings.reading_count,
        readings.peak_battery_temp_c,
        readings.mean_battery_temp_c,
        readings.min_cpu_speed_limit,
        readings.throttled_reading_count,
        readings.min_battery_pct,
        readings.mean_ollama_cpu,
        GREATEST(runs.started_at, readings.last_read_at) AS last_seen_at,
        {{ safe_divide('readings.on_battery_reading_count', 'readings.reading_count') }}
            AS on_battery_share
    FROM {{ ref('stg_eval_run_log') }} AS runs
    LEFT JOIN readings ON runs.run_id = readings.run_id

)

SELECT
    *,
    CASE
        WHEN
            status = 'running'
            AND last_seen_at
            < CAST('{{ var("health_as_of", run_started_at) }}' AS TIMESTAMPTZ)
            - TO_MINUTES({{ var('run_stale_minutes') }})
            THEN 'abandoned'
        ELSE status
    END AS outcome,
    COALESCE(throttled_reading_count > 0, FALSE) AS was_throttled,
    {{ safe_divide('done_samples', 'total_samples') }} AS completion_share
FROM joined
