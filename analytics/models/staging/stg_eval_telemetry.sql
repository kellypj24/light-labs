{# One row per heat and load reading during an eval run. #}

WITH source AS (

    SELECT *
    FROM {{ source('raw', 'eval_telemetry') }}

),

renamed AS (

    SELECT
        run_id,
        battery_temp_c,
        battery_pct,
        cpu_speed_limit,
        thermal_warning,
        load_1,
        ollama_cpu,
        "at" AS read_at,  -- noqa: RF06
        on_ac AS is_on_ac,
        run_id || '|' || CAST("at" AS VARCHAR) AS reading_key,  -- noqa: RF06
        COALESCE(cpu_speed_limit < 100, FALSE) AS is_throttled
    FROM source

)

SELECT * FROM renamed
