{# One row per fitted calibration map. #}

WITH source AS (

    SELECT *
    FROM {{ source('raw', 'calibration_maps') }}

),

renamed AS (

    SELECT
        robot,
        question,
        brain,
        method,
        status,
        n AS pair_count,
        positives AS positive_count,
        brier_raw,
        brier_cal,
        ece_raw,
        ece_cal,
        params,
        CAST(built AS TIMESTAMPTZ) AS built_at,
        robot || '|' || question || '|' || brain AS map_key
    FROM source

)

SELECT * FROM renamed
