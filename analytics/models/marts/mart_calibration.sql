{#
    One row per robot, question and brain that has shadow pairs: how many, how many
    lack a brain (never fitted), and the map's method and scores. Brier and ECE gains
    are raw minus held-out calibrated, so positive is better; NULL for identity maps
    that never fitted. A question whose pairs all lack a brain has no map row.
#}

WITH pairs AS (

    SELECT
        robot,
        question,
        COALESCE(brain, '(unrecorded)') AS brain,
        COUNT(*) AS pair_count,
        COUNT(*) FILTER (WHERE is_positive) AS positive_count,
        AVG(p_raw) AS mean_p_raw,
        AVG(CAST(is_positive AS INTEGER)) AS positive_rate,
        MAX(answered_at) AS last_answered_at
    FROM {{ ref('stg_shadow_pairs') }}
    GROUP BY robot, question, COALESCE(brain, '(unrecorded)')

),

maps AS (

    SELECT * FROM {{ ref('stg_calibration_maps') }}

),

joined AS (

    SELECT
        pairs.robot,
        pairs.question,
        pairs.brain,
        pairs.pair_count,
        pairs.positive_count,
        pairs.mean_p_raw,
        pairs.positive_rate,
        pairs.last_answered_at,
        maps.built_at,
        maps.brier_raw,
        maps.brier_cal,
        maps.ece_raw,
        maps.ece_cal,
        pairs.robot || '|' || pairs.question || '|' || pairs.brain AS calibration_key,
        COALESCE(maps.method, 'identity') AS calibration_method,
        COALESCE(maps.status, 'no-brain') AS map_status,
        pairs.mean_p_raw - pairs.positive_rate AS overconfidence,
        maps.brier_raw - maps.brier_cal AS brier_gain,
        maps.ece_raw - maps.ece_cal AS ece_gain
    FROM pairs
    LEFT JOIN maps
        ON
            pairs.robot = maps.robot
            AND pairs.question = maps.question
            AND pairs.brain = maps.brain

)

SELECT * FROM joined
