-- Notes quality — does the engine's document earn trust (Summary Engine v2,
-- Q6 T8)?
--
-- One row per (ISO week, dimension, bucket, metric), counts only:
--   week         the Monday of the week the generation finished (for shares:
--                the week of the first share; for titles and types: the
--                week the note was created)
--   dimension    all | recording_type | language | kind | reason
--   bucket       a closed vocabulary; anything else folds into 'other'
--   metric       kept_line_rate | dismiss_rate | dismiss_reason |
--                regenerate_rate | share_without_edit | minutes_to_first_share |
--                corrections_accepted | type_changed | title_changed
--   numerator, denominator, value (a percentage; for minutes_to_first_share
--                the median minutes, with numerator = shares timed)
--
-- Run as `funnel_reader` (migrations 0040, 0046, 0060) — scripts/jobs/
-- weekly_notes_quality.py does. The role reads metadata columns only; the
-- two numbers that compare written lines with the note's current text come
-- from 0060's SECURITY DEFINER functions, which return ids and integers.
-- No tenant or workspace id leaves the database: every row is aggregated
-- across workspaces.
--
-- Approximations (docs/runbooks/notes.md, "Weekly notes quality"):
--   kept line    the written line's text, marker off, is still in the note
--                7 days later — word for word, so an edited owner or date
--                counts as not kept (a LOWER bound on the item-key rule)
--   dismiss      `note_item_corrections.action = 'dismiss'` on a line the
--                generation wrote, over the lines it wrote
--   type_changed the author set a meeting type after the classifier chose
--                one (`detected_by = 'model'` and `meeting_type <> 'auto'`);
--                a later regeneration makes it `detected_by = 'user'`, so
--                this is a LOWER bound
--   evidence opened per line is not reported: no evidence-opened metric or
--                event exists yet

WITH gens AS (
    SELECT
        g.id, g.note_id, g.reason, g.created_at, g.finished_at,
        date_trunc('week', g.finished_at)::date                            AS week,
        CASE WHEN g.stats->>'recording_type' IN
                  ('meeting', 'one_on_one', 'interview', 'sales_call', 'client_call',
                   'lecture_webinar', 'podcast_broadcast', 'voice_memo', 'other')
             THEN g.stats->>'recording_type' ELSE 'unknown' END              AS recording_type,
        CASE WHEN g.stats->>'language' ~ '^[a-z]{2}$'
             THEN g.stats->>'language' ELSE 'other' END                      AS language
    FROM note_generations g
    WHERE g.status = 'complete' AND g.finished_at IS NOT NULL
),
dims AS (
    -- Every generation once per dimension it is counted under.
    SELECT id, week, 'all' AS dimension, 'all' AS bucket FROM gens
    UNION ALL SELECT id, week, 'recording_type', recording_type FROM gens
    UNION ALL SELECT id, week, 'language', language FROM gens
),
written AS (
    SELECT i.generation_id,
           count(*)                                         AS lines,
           CASE WHEN i.kind IN ('summary_sentence', 'framing', 'topic_bullet', 'date',
                                'action', 'decision', 'key_point', 'question', 'risk',
                                'agreement', 'judgement')
                THEN i.kind ELSE 'other' END                AS kind
    FROM note_generated_items i
    JOIN gens g ON g.id = i.generation_id
    WHERE i.placement IN ('written', 'dismissed')
    GROUP BY i.generation_id, 3
),
dismissed AS (
    SELECT i.generation_id, w.kind,
           coalesce(c.reason, 'none')                       AS reason
    FROM note_item_corrections c
    JOIN note_generated_items i
      ON i.note_id = c.note_id AND i.item_key = c.item_key
     AND i.placement IN ('written', 'dismissed')
    JOIN gens g ON g.id = i.generation_id
    JOIN LATERAL (
        SELECT CASE WHEN i.kind IN ('summary_sentence', 'framing', 'topic_bullet', 'date',
                                    'action', 'decision', 'key_point', 'question', 'risk',
                                    'agreement', 'judgement')
                    THEN i.kind ELSE 'other' END AS kind
    ) w ON true
    WHERE c.action = 'dismiss' AND c.created_at >= g.finished_at
),
kept AS (
    SELECT k.generation_id, k.lines_written, k.lines_kept
    FROM notes_quality_kept_lines() k
),
first_done AS (
    -- Per note: its first complete generation.
    SELECT DISTINCT ON (note_id) note_id, id, week, recording_type, language, finished_at
    FROM gens ORDER BY note_id, finished_at
),
regenerated AS (
    SELECT f.id, count(*) AS regenerations
    FROM note_generations r
    JOIN first_done f ON f.note_id = r.note_id
    WHERE r.reason = 'regenerate' AND r.created_at >= f.finished_at
    GROUP BY f.id
),
shares AS (
    SELECT f.id AS first_id, s.unedited, date_trunc('week', s.shared_at)::date AS week,
           extract(epoch FROM (s.shared_at - f.finished_at)) / 60.0          AS minutes
    FROM notes_quality_shares() s
    JOIN first_done f ON f.note_id = s.note_id
),
offered AS (
    SELECT o.generation_id, o.offered FROM notes_quality_corrections_offered() o
),
accepted AS (
    SELECT i.generation_id, count(*) AS accepted
    FROM note_item_corrections c
    JOIN note_generated_items i
      ON i.note_id = c.note_id AND i.item_key = c.item_key
     AND i.placement IN ('written', 'dismissed')
    JOIN gens g ON g.id = i.generation_id
    WHERE c.action = 'correction_accepted' AND c.created_at >= g.finished_at
    GROUP BY i.generation_id
),
rows AS (
    -- kept-line rate (7 d)
    SELECT d.week, d.dimension, d.bucket, 'kept_line_rate' AS metric,
           sum(k.lines_kept) AS numerator, sum(k.lines_written) AS denominator
    FROM dims d JOIN kept k ON k.generation_id = d.id
    GROUP BY 1, 2, 3
    UNION ALL
    -- dismiss rate, by generation dimensions
    SELECT d.week, d.dimension, d.bucket, 'dismiss_rate',
           coalesce(sum(x.n), 0), sum(w.lines)
    FROM dims d
    JOIN (SELECT generation_id, sum(lines) AS lines FROM written GROUP BY 1) w
      ON w.generation_id = d.id
    LEFT JOIN (SELECT generation_id, count(*) AS n FROM dismissed GROUP BY 1) x
      ON x.generation_id = d.id
    GROUP BY 1, 2, 3
    UNION ALL
    -- dismiss rate, by kind
    SELECT g.week, 'kind', w.kind, 'dismiss_rate',
           coalesce(sum(x.n), 0), sum(w.lines)
    FROM written w
    JOIN gens g ON g.id = w.generation_id
    LEFT JOIN (SELECT generation_id, kind, count(*) AS n FROM dismissed GROUP BY 1, 2) x
      ON x.generation_id = w.generation_id AND x.kind = w.kind
    GROUP BY 1, 2, 3
    UNION ALL
    -- the reasons people give (not_said is the faithfulness signal)
    SELECT g.week, 'reason', x.reason, 'dismiss_reason',
           count(*), sum(count(*)) OVER (PARTITION BY g.week)
    FROM dismissed x JOIN gens g ON g.id = x.generation_id
    GROUP BY 1, 2, 3
    UNION ALL
    -- regenerate rate: regenerations ÷ notes with a complete generation
    SELECT d.week, d.dimension, d.bucket, 'regenerate_rate',
           coalesce(sum(rg.regenerations), 0), count(*)
    FROM first_done f
    JOIN dims d ON d.id = f.id
    LEFT JOIN regenerated rg ON rg.id = f.id
    GROUP BY 1, 2, 3
    UNION ALL
    -- share-without-edit: shared notes whose engine sections were untouched
    SELECT s.week, d.dimension, d.bucket, 'share_without_edit',
           count(*) FILTER (WHERE s.unedited), count(*) FILTER (WHERE s.unedited IS NOT NULL)
    FROM shares s JOIN dims d ON d.id = s.first_id
    GROUP BY 1, 2, 3
    UNION ALL
    -- corrections accepted ÷ offered
    SELECT d.week, d.dimension, d.bucket, 'corrections_accepted',
           coalesce(sum(a.accepted), 0), sum(o.offered)
    FROM dims d
    JOIN offered o ON o.generation_id = d.id
    LEFT JOIN accepted a ON a.generation_id = d.id
    GROUP BY 1, 2, 3
),
timed AS (
    SELECT s.week, d.dimension, d.bucket, 'minutes_to_first_share' AS metric,
           count(*) AS numerator, NULL::bigint AS denominator,
           round((percentile_cont(0.5) WITHIN GROUP (ORDER BY s.minutes))::numeric, 1) AS value
    FROM shares s JOIN dims d ON d.id = s.first_id
    GROUP BY 1, 2, 3
),
names AS (
    -- the classifier's type, changed by the author afterwards
    SELECT date_trunc('week', n.created_at)::date AS week, 'all' AS dimension, 'all' AS bucket,
           'type_changed' AS metric,
           count(*) FILTER (WHERE m.meeting_type <> 'auto') AS numerator,
           count(*) AS denominator
    FROM note_meetings m JOIN notes n ON n.id = m.note_id
    WHERE m.detected_by = 'model'
    GROUP BY 1
    UNION ALL
    -- the AI title, renamed by a person
    SELECT date_trunc('week', n.created_at)::date, 'all', 'all', 'title_changed',
           count(*) FILTER (WHERE n.title_source = 'user'), count(*)
    FROM notes n
    WHERE n.title_generated_at IS NOT NULL AND n.deleted_at IS NULL
    GROUP BY 1
)
SELECT week, dimension, bucket, metric, numerator, denominator,
       round(100.0 * numerator / nullif(denominator, 0), 2) AS value
FROM rows
UNION ALL
SELECT week, dimension, bucket, metric, numerator, denominator,
       round(100.0 * numerator / nullif(denominator, 0), 2)
FROM names
UNION ALL
SELECT week, dimension, bucket, metric, numerator, denominator, value
FROM timed
ORDER BY week DESC, metric, dimension, bucket;
