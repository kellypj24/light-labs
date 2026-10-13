{# One row per eval run's lifecycle record. #}

WITH source AS (

    SELECT *
    FROM {{ source('raw', 'eval_run_log') }}

),

renamed AS (

    SELECT
        run_id,
        stage,
        contestants,
        status,
        started_at,
        ended_at,
        samples AS samples_per_fixture,
        total AS total_samples,
        done AS done_samples,
        passed AS passed_samples,
        harness_errors AS harness_error_count,
        cool_pauses AS cool_pause_count,
        cool_seconds,
        cool_above_c,
        reason AS stop_reason,
        "commit" AS git_commit,  -- noqa: RF06
        dirty AS is_dirty,
        source AS source_file,
        NULLIF("filter", '') AS fixture_filter,  -- noqa: RF06
        DATE_DIFF('second', started_at, ended_at) / 60.0 AS duration_minutes
    FROM source

)

SELECT * FROM renamed
