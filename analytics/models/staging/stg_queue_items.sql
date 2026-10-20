{#
    One row per queued draft. A draft Rush replaced with a newer one for the same thread,
    or dropped when PJ muted the thread, is superseded; an escalation Auto closed with no
    reply is noted. Both are rejected on disk, but no decision of PJ's, so they count as
    neither decided nor rejected. A sent draft is edited when the text sent differs from
    what the robot wrote; NULL when that is unknown (queued before `drafted` was
    recorded) or the draft was not sent.
#}

WITH source AS (

    SELECT *
    FROM {{ source('raw', 'queue_items') }}

),

renamed AS (

    SELECT
        item_id,
        robot,
        status,
        kind,
        escalation,
        context,
        brain,
        result_id,
        draft AS sent_text,
        drafted AS drafted_text,
        created AS created_at,
        resolved AS resolved_at,
        reason AS reject_reason,
        "commit" AS git_commit,  -- noqa: RF06
        dirty AS is_dirty,
        source AS source_file,
        flag_reason,
        held AS held_reasons,
        COALESCE(auto, FALSE) AS is_auto,
        COALESCE(flagged, FALSE) AS is_flagged,
        robot || '|' || item_id AS queue_item_key,
        target ->> '$.task_id' AS task_id,
        escalation IS NOT NULL AS is_escalated,
        status = 'rejected' AND COALESCE(STARTS_WITH(reason, 'superseded by '), FALSE)
            AS is_superseded,
        status = 'rejected' AND COALESCE(STARTS_WITH(reason, 'noted by Auto: '), FALSE)
            AS is_noted,
        status = 'sent'
        OR (
            status = 'rejected'
            AND NOT COALESCE(REGEXP_MATCHES(reason, '^(superseded by|noted by Auto:) '), FALSE)
        ) AS is_decided,
        status = 'sent' AS is_sent,
        status = 'rejected'
        AND NOT COALESCE(REGEXP_MATCHES(reason, '^(superseded by|noted by Auto:) '), FALSE)
            AS is_rejected,
        DATE_DIFF('minute', created, resolved) AS minutes_to_decision,
        CASE
            WHEN status <> 'sent' OR drafted IS NULL THEN NULL
            ELSE draft <> drafted
        END AS is_edited,
        CASE
            WHEN status <> 'sent' OR drafted IS NULL THEN NULL
            ELSE 1 - {{ safe_divide('LEVENSHTEIN(draft, drafted)',
                'GREATEST(LENGTH(draft), LENGTH(drafted))') }}
        END AS edit_similarity
    FROM source

)

SELECT * FROM renamed
