{#
    One row per robot, draft kind and day the drafts were queued: how many were sent,
    rejected or still pending, how many went out exactly as drafted, and how long
    decisions took.
#}

SELECT
    robot || '|' || kind || '|' || CAST(CAST(created_at AS DATE) AS VARCHAR) AS queue_day_key,
    robot,
    kind,
    CAST(created_at AS DATE) AS queued_date,
    COUNT(*) AS drafted_count,
    COUNT(*) FILTER (WHERE status = 'pending') AS pending_count,
    COUNT(*) FILTER (WHERE is_sent) AS sent_count,
    COUNT(*) FILTER (WHERE is_rejected) AS rejected_count,
    COUNT(*) FILTER (WHERE is_sent AND NOT is_edited) AS unedited_sent_count,
    COUNT(*) FILTER (WHERE is_sent AND is_edited) AS edited_sent_count,
    COUNT(*) FILTER (WHERE is_escalated) AS escalated_count,
    {{ safe_divide('COUNT(*) FILTER (WHERE is_sent)', 'COUNT(*) FILTER (WHERE is_decided)') }}
        AS approval_rate,
    MEDIAN(minutes_to_decision) AS median_minutes_to_decision
FROM {{ ref('stg_queue_items') }}
GROUP BY robot, kind, CAST(created_at AS DATE)
