-- Speaker quality: the weekly learn-loop cohort.
--
-- One row per (ISO week of job completion, dimension, bucket), counts only.
-- Definitions and every approximation: docs/product/speaker-metrics.md.
-- Run as `funnel_reader` (column-level subset; cannot read speaker names).
-- Cohort: complete, diarized jobs finished MORE than 7 days ago; a job with
-- no correction counts as correct, so every accuracy number is an UPPER BOUND.
--
-- Dimensions (closed vocabularies; anything else folds into 'other'):
--   all               one row per week
--   engine            metadata.diarization.engine (current revision)
--   hint              exact | max | none   (the request's speaker hint)
--   client            web | ios | macos | other | unknown   (capture_context.client)
--   source            calendar_event | manual | upload | other | unknown
--   count_confidence  high | low | unknown (pre-Sprint-29 results)
--   channel_layout    mic_system | mono_fallback | mono   (what the worker diarized)

WITH jobs AS (
    SELECT
        j.id,
        date_trunc('week', j.finished_at)::date                          AS week,
        j.result_first_read_at IS NOT NULL                                AS opened,
        j.diarization_runs                                                AS runs,
        j.diarization_rev                                                 AS rev,
        CASE WHEN j.metadata->'diarization'->>'engine' ~ '^[a-z0-9._-]{1,40}$'
             THEN j.metadata->'diarization'->>'engine' ELSE 'other' END    AS engine,
        CASE WHEN j.metadata->'diarization'->>'hint_num_speakers' IS NOT NULL THEN 'exact'
             WHEN j.metadata->'diarization'->>'hint_max_speakers' IS NOT NULL THEN 'max'
             ELSE 'none' END                                              AS hint,
        CASE WHEN j.capture_context->>'client' IN ('web', 'ios', 'macos')
             THEN j.capture_context->>'client'
             WHEN j.capture_context ? 'client' THEN 'other'
             ELSE 'unknown' END                                           AS client,
        CASE WHEN j.capture_context->>'source' IN ('calendar_event', 'manual', 'upload')
             THEN j.capture_context->>'source'
             WHEN j.capture_context ? 'source' THEN 'other'
             ELSE 'unknown' END                                           AS source,
        CASE WHEN j.metadata->'diarization'->>'count_confidence' IN ('high', 'low')
             THEN j.metadata->'diarization'->>'count_confidence'
             ELSE 'unknown' END                                           AS count_confidence,
        CASE WHEN j.metadata->'diarization'->>'channel_layout' IN ('mic_system', 'mono_fallback')
             THEN j.metadata->'diarization'->>'channel_layout'
             ELSE 'mono' END                                              AS channel_layout
    FROM transcription_jobs j
    WHERE j.status = 'complete'
      AND jsonb_typeof(j.metadata->'diarization') = 'object'
      AND j.finished_at < now() - interval '7 days'
),
edits AS (
    -- Per job: live (not reverted) edits of any revision, and — for the
    -- count error — the roster changes of revision 1's live edits.
    SELECT
        e.job_id,
        count(*) FILTER (WHERE e.reverted_at IS NULL AND e.kind = 'merge')      AS live_merges,
        count(*) FILTER (WHERE e.reverted_at IS NULL AND e.kind = 'reassign')   AS live_reassigns,
        count(*) FILTER (WHERE e.reverted_at IS NOT NULL)                       AS reverted,
        count(*) FILTER (WHERE e.reverted_at IS NULL AND e.creates_label)       AS labels_created,
        count(DISTINCT e.from_label) FILTER (
            WHERE e.reverted_at IS NULL AND e.kind = 'merge' AND e.result_rev = 1) AS rev1_merged_away,
        count(DISTINCT e.to_label) FILTER (
            WHERE e.reverted_at IS NULL AND e.creates_label AND e.result_rev = 1)  AS rev1_created,
        count(*) FILTER (
            WHERE e.reverted_at IS NULL AND e.result_rev = 2)                   AS rev2_live_edits
    FROM transcription_speaker_edits e
    JOIN jobs c ON c.id = e.job_id
    GROUP BY e.job_id
),
per_job AS (
    SELECT
        c.*,
        coalesce(ed.live_merges, 0)     AS live_merges,
        coalesce(ed.live_reassigns, 0)  AS live_reassigns,
        coalesce(ed.reverted, 0)        AS reverted,
        coalesce(ed.labels_created, 0)  AS labels_created,
        (coalesce(ed.live_merges, 0) + coalesce(ed.live_reassigns, 0) > 0 OR c.runs > 0)
                                        AS corrected,
        -- count error = merged away − created, from the edits alone; only for
        -- jobs never re-run (a re-run overwrites metadata.diarization).
        CASE WHEN c.runs = 0
             THEN coalesce(ed.rev1_merged_away, 0) - coalesce(ed.rev1_created, 0)
        END                             AS count_error,
        coalesce(ed.rev2_live_edits, 0) AS rev2_live_edits
    FROM jobs c
    LEFT JOIN edits ed ON ed.job_id = c.id
)
SELECT
    p.week,
    g.dimension,
    g.bucket,
    count(*)                                                                  AS diarized_jobs,
    count(*) FILTER (WHERE p.opened)                                          AS opened_jobs,
    count(*) FILTER (WHERE p.opened AND p.corrected)                          AS corrected_jobs,
    round(100.0 * count(*) FILTER (WHERE p.opened AND p.corrected)
          / nullif(count(*) FILTER (WHERE p.opened), 0), 2)                   AS correction_rate_pct,
    count(*) FILTER (WHERE p.opened AND p.live_merges > 0)                    AS jobs_merged,
    count(*) FILTER (WHERE p.opened AND p.live_reassigns > 0)                 AS jobs_reassigned,
    count(*) FILTER (WHERE p.opened AND p.runs > 0)                           AS jobs_rediarized,
    coalesce(sum(p.live_merges) FILTER (WHERE p.opened), 0)                   AS merge_edits,
    coalesce(sum(p.live_reassigns) FILTER (WHERE p.opened), 0)                AS reassign_edits,
    coalesce(sum(p.runs) FILTER (WHERE p.opened), 0)                          AS rediarize_runs,
    coalesce(sum(p.reverted) FILTER (WHERE p.opened), 0)                      AS reverted_edits,
    coalesce(sum(p.labels_created) FILTER (WHERE p.opened), 0)                AS labels_created,
    count(p.count_error) FILTER (WHERE p.opened)                              AS count_scored_jobs,
    round(avg(abs(p.count_error)) FILTER (WHERE p.opened), 3)                 AS count_error_mean_abs,
    round(avg(p.count_error) FILTER (WHERE p.opened), 3)                      AS count_error_mean_signed,
    round(100.0 * count(*) FILTER (WHERE p.opened AND p.count_error > 0)
          / nullif(count(p.count_error) FILTER (WHERE p.opened), 0), 2)       AS overcount_pct,
    round(100.0 * count(*) FILTER (WHERE p.opened AND p.count_error < 0)
          / nullif(count(p.count_error) FILTER (WHERE p.opened), 0), 2)       AS undercount_pct,
    -- Re-run outcomes, reconstructed from (runs, rev): see the doc.
    count(*) FILTER (WHERE p.opened AND p.runs = 1 AND p.rev = 2)             AS rediarize_kept,
    count(*) FILTER (WHERE p.opened AND p.runs = 1 AND p.rev = 2
                       AND p.rev2_live_edits > 0)                             AS rediarize_kept_then_edited,
    count(*) FILTER (WHERE p.opened AND p.runs = 1 AND p.rev = 3)             AS rediarize_undone,
    count(*) FILTER (WHERE p.opened AND p.runs = 1 AND p.rev = 1)             AS rediarize_failed,
    count(*) FILTER (WHERE p.opened AND p.runs >= 2)                          AS rediarize_repeated,
    round(100.0 * count(*) FILTER (WHERE p.opened AND p.runs = 1 AND p.rev = 2)
          / nullif(count(*) FILTER (WHERE p.opened AND p.runs > 0), 0), 2)    AS rediarize_success_pct
FROM per_job p
CROSS JOIN LATERAL (VALUES
    ('all', 'all'),
    ('engine', p.engine),
    ('hint', p.hint),
    ('client', p.client),
    ('source', p.source),
    ('count_confidence', p.count_confidence),
    ('channel_layout', p.channel_layout)
) AS g(dimension, bucket)
GROUP BY p.week, g.dimension, g.bucket
ORDER BY p.week DESC, g.dimension, g.bucket;
