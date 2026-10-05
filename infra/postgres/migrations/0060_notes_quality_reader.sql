-- 0060 — Summary Engine v2, Q6 T8: the weekly notes-quality report reads as
-- funnel_reader.
--
-- scripts/ops/notes_quality.sql counts, across every tenant, whether people
-- keep, dismiss, regenerate and share what the engine writes. Like 0046 the
-- grants are COLUMN-LEVEL and stop at metadata:
--
--   note_generations       id, tenant_id, note_id, reason, status, stats
--                          (counts, hashes, recording type, language — the
--                          table's own rule: "never content"), created_at,
--                          finished_at
--   note_generated_items   id, tenant_id, note_id, generation_id, item_key,
--                          kind, placement, created_at
--                          NOT text, quote, owner/due, speaker, corrections,
--                          mentions, attributed_to
--   note_item_corrections  id, tenant_id, note_id, item_key, kind, action,
--                          reason, created_at — NOT actor_sub
--   note_meetings          note_id, tenant_id, meeting_type,
--                          meeting_type_detected, detected_by, created_at
--                          NOT calendar_context (attendee names, agenda)
--
-- Two of the report's numbers compare what was written with what the note
-- says now (kept lines; shared without an edit), and one counts the name
-- corrections offered. Those read content, so they are SECURITY DEFINER
-- functions that return ids and integers only; funnel_reader may call them
-- and still cannot read a note's text, a quote or a name.
--
-- The four tables' RESTRICTIVE tenant policies are already TO app_role
-- (0049/0050/0052), so a permissive policy for funnel_reader is enough.

GRANT SELECT (id, tenant_id, note_id, reason, status, stats, created_at, finished_at)
    ON note_generations TO funnel_reader;
GRANT SELECT (id, tenant_id, note_id, generation_id, item_key, kind, placement, created_at)
    ON note_generated_items TO funnel_reader;
GRANT SELECT (id, tenant_id, note_id, item_key, kind, action, reason, created_at)
    ON note_item_corrections TO funnel_reader;
GRANT SELECT (note_id, tenant_id, meeting_type, meeting_type_detected, detected_by, created_at)
    ON note_meetings TO funnel_reader;

CREATE POLICY funnel_reader_select ON note_generations
    FOR SELECT TO funnel_reader USING (true);
CREATE POLICY funnel_reader_select ON note_generated_items
    FOR SELECT TO funnel_reader USING (true);
CREATE POLICY funnel_reader_select ON note_item_corrections
    FOR SELECT TO funnel_reader USING (true);
CREATE POLICY funnel_reader_select ON note_meetings
    FOR SELECT TO funnel_reader USING (true);

-- A written line with its list marker and runs of whitespace taken off,
-- the way it would sit inside a section's text.
CREATE OR REPLACE FUNCTION notes_quality_bare(line TEXT)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
    SELECT btrim(regexp_replace(
        regexp_replace(line, '^\s*([-*•]|\d+[.)])\s+', ''), '\s+', ' ', 'g'))
$$;

-- Per complete generation that finished 7 days to 12 weeks ago: how many
-- lines it wrote, and how many of them the note still says, word for word,
-- in the version that was current 7 days after it finished. A line whose
-- owner or date the author changed counts as not kept (stricter than the
-- item key, which ignores both).
CREATE OR REPLACE FUNCTION notes_quality_kept_lines()
RETURNS TABLE (generation_id UUID, lines_written INTEGER, lines_kept INTEGER)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    WITH gens AS (
        SELECT g.id, g.note_id, g.finished_at
          FROM note_generations g
         WHERE g.status = 'complete'
           AND g.finished_at <  now() - interval '7 days'
           AND g.finished_at >= now() - interval '12 weeks'
    ),
    body AS (
        SELECT g.id AS generation_id,
               regexp_replace(coalesce(string_agg(s->>'text', ' '), ''), '\s+', ' ', 'g') AS text
          FROM gens g
          CROSS JOIN LATERAL (
              SELECT v.content_jsonb
                FROM note_versions v
               WHERE v.note_id = g.note_id
                 AND v.created_at <= g.finished_at + interval '7 days'
               ORDER BY v.version_number DESC
               LIMIT 1
          ) v
          CROSS JOIN LATERAL jsonb_array_elements(
              CASE WHEN jsonb_typeof(v.content_jsonb->'sections') = 'array'
                   THEN v.content_jsonb->'sections' ELSE '[]'::jsonb END) s
         GROUP BY g.id
    )
    SELECT i.generation_id,
           count(*)::int,
           count(*) FILTER (
               WHERE strpos(b.text, notes_quality_bare(i.text)) > 0)::int
      FROM note_generated_items i
      JOIN body b ON b.generation_id = i.generation_id
     WHERE i.placement IN ('written', 'dismissed')
     GROUP BY i.generation_id
$$;

-- Per shared note (its first share link): the complete generation it was
-- shared from, and whether every section the engine wrote still hashes to
-- what the engine wrote (`stats.section_hashes`) in the version current
-- when it was shared.
CREATE OR REPLACE FUNCTION notes_quality_shares()
RETURNS TABLE (note_id UUID, generation_id UUID, shared_at TIMESTAMPTZ, unedited BOOLEAN)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    WITH first_share AS (
        SELECT l.note_id, min(l.created_at) AS shared_at
          FROM note_share_links l
         GROUP BY l.note_id
    ),
    shared AS (
        SELECT f.note_id, f.shared_at, g.id AS generation_id, g.stats
          FROM first_share f
          CROSS JOIN LATERAL (
              SELECT g.id, g.stats
                FROM note_generations g
               WHERE g.note_id = f.note_id
                 AND g.status IN ('complete', 'superseded')
                 AND g.finished_at <= f.shared_at
               ORDER BY g.finished_at DESC
               LIMIT 1
          ) g
    )
    SELECT s.note_id, s.generation_id, s.shared_at,
           -- NULL when the generation recorded no hashes (unknown, not "edited").
           bool_and(
               encode(sha256(convert_to(coalesce(sec->>'text', ''), 'UTF8')), 'hex')
                   = h.value #>> '{}')
      FROM shared s
      CROSS JOIN LATERAL (
          SELECT v.content_jsonb
            FROM note_versions v
           WHERE v.note_id = s.note_id AND v.created_at <= s.shared_at
           ORDER BY v.version_number DESC
           LIMIT 1
      ) v
      LEFT JOIN LATERAL jsonb_each(
          CASE WHEN jsonb_typeof(s.stats->'section_hashes') = 'object'
               THEN s.stats->'section_hashes' ELSE '{}'::jsonb END) h ON true
      LEFT JOIN LATERAL (
          SELECT e AS sec
            FROM jsonb_array_elements(
                CASE WHEN jsonb_typeof(v.content_jsonb->'sections') = 'array'
                     THEN v.content_jsonb->'sections' ELSE '[]'::jsonb END) e
           WHERE e->>'section_key' = h.key
           LIMIT 1
      ) x ON true
     GROUP BY s.note_id, s.generation_id, s.shared_at
$$;

-- Per generation: how many name corrections (Q4) its written lines offer.
CREATE OR REPLACE FUNCTION notes_quality_corrections_offered()
RETURNS TABLE (generation_id UUID, offered INTEGER)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT i.generation_id, sum(jsonb_array_length(i.corrections))::int
      FROM note_generated_items i
     WHERE i.placement IN ('written', 'dismissed')
       AND jsonb_typeof(i.corrections) = 'array'
       AND jsonb_array_length(i.corrections) > 0
     GROUP BY i.generation_id
$$;

REVOKE ALL ON FUNCTION notes_quality_kept_lines() FROM PUBLIC;
REVOKE ALL ON FUNCTION notes_quality_shares() FROM PUBLIC;
REVOKE ALL ON FUNCTION notes_quality_corrections_offered() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION notes_quality_kept_lines() TO funnel_reader;
GRANT EXECUTE ON FUNCTION notes_quality_shares() TO funnel_reader;
GRANT EXECUTE ON FUNCTION notes_quality_corrections_offered() TO funnel_reader;
