{# One row per shadow pair: a local answer's raw p and its label. #}

WITH source AS (

    SELECT *
    FROM {{ source('raw', 'shadow_pairs') }}

),

renamed AS (

    SELECT
        robot,
        question,
        brain,
        p AS p_raw,
        label AS is_positive,
        source_id,
        label_by,
        CAST("at" AS TIMESTAMPTZ) AS answered_at,  -- noqa: RF06
        brain IS NOT NULL AS has_brain
    FROM source

)

SELECT * FROM renamed
