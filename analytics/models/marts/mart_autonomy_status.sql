{#
    One row per robot and draft kind: could this kind skip approval? Judged on the
    last `autonomy_window` decisions (sent or rejected), all of which must exist: ready
    when at least `autonomy_min_unedited_rate` of them were sent exactly as drafted.
    Rejections, edits, and edits unknown all count against it. Auto-sent drafts are not
    PJ's decisions and are left out, except flagged ones, which count as corrections.
#}

WITH ranked AS (

    SELECT
        robot,
        kind,
        is_edited,
        is_escalated,
        resolved_at,
        is_sent AND NOT COALESCE(is_flagged, FALSE) AS is_sent,
        ROW_NUMBER() OVER (
            PARTITION BY robot, kind ORDER BY resolved_at DESC
        ) AS recency
    FROM {{ ref('stg_queue_items') }}
    WHERE is_decided AND (NOT COALESCE(is_auto, FALSE) OR COALESCE(is_flagged, FALSE))

),

windowed AS (

    SELECT
        robot,
        kind,
        COUNT(*) AS decision_count,
        COUNT(*) FILTER (WHERE is_sent AND is_edited = FALSE) AS unedited_sent_count,
        COUNT(*) FILTER (WHERE is_sent AND is_edited) AS edited_sent_count,
        COUNT(*) FILTER (WHERE is_sent AND is_edited IS NULL) AS unknown_edit_count,
        COUNT(*) FILTER (WHERE NOT is_sent) AS rejected_count,
        COUNT(*) FILTER (WHERE is_escalated) AS escalated_count,
        MIN(resolved_at) AS window_start,
        MAX(resolved_at) AS window_end
    FROM ranked
    WHERE recency <= {{ var('autonomy_window') }}
    GROUP BY robot, kind

)

SELECT
    robot || '|' || kind AS robot_kind_key,
    *,
    {{ safe_divide('unedited_sent_count', 'decision_count') }} AS unedited_rate,
    {{ var('autonomy_window') }} AS window_size,
    COALESCE(
        decision_count >= {{ var('autonomy_window') }}
        AND unedited_sent_count::DOUBLE / decision_count
        >= {{ var('autonomy_min_unedited_rate') }},
        FALSE
    ) AS is_ready_to_skip_approval
FROM windowed
