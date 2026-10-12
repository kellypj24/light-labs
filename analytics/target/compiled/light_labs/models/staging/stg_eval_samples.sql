

WITH source AS (

    SELECT *
    FROM "lab"."raw"."eval_samples"

),

renamed AS (

    SELECT
        run_id,
        stage,
        contestant,
        role,
        brain,
        fixture,
        category,
        sample AS sample_number,
        passed AS is_passed,
        draft,
        latency_s AS latency_seconds,
        isolated AS is_isolated,
        "commit" AS git_commit,  -- noqa: RF06
        dirty AS is_dirty,
        checks,
        "at" AS sampled_at,  -- noqa: RF06
        source AS source_file,
        run_id || '|' || contestant || '|' || fixture || '|' || sample AS sample_key,
        -- The scorer's first check is `ran`; it fails alone when the runner
        -- or the model call broke, which is not the model's fault.
        COALESCE(
            checks -> '$[0]' ->> 'name' = 'ran'
            AND NOT CAST(checks -> '$[0]' ->> 'passed' AS BOOLEAN),
            FALSE
        ) AS is_harness_error,
        NULLIF(escalate, '') AS escalation,
        NULLIF(escalate, '') IS NOT NULL AS is_escalated,
        LENGTH(draft) AS draft_chars,
        COALESCE(cost_usd, 0) AS cost_usd,
        NULLIF("filter", '') AS fixture_filter,  -- noqa: RF06
        NULLIF(error, '') AS error
    FROM source

)

SELECT * FROM renamed
