-- 0058 — recording types (Summary Engine v2, Q3).
--
-- `note_meetings.meeting_type_detected` (0051) could only say which kind of
-- MEETING a recording was. A news podcast, a lecture and a voice memo are
-- not meetings, and the engine now extracts them with families of their
-- own (no Decisions, no Tasks on a broadcast). This widens the column's
-- vocabulary; nothing else changes. No new table, no backfill: older rows
-- keep the values they have.
--
-- The 0051 CHECK was declared inline on the column, so Postgres named it;
-- it is found by what it constrains rather than by an assumed name.

DO $$
DECLARE
    old_check TEXT;
BEGIN
    SELECT conname INTO old_check
    FROM pg_constraint
    WHERE conrelid = 'note_meetings'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%meeting_type_detected%';
    IF old_check IS NOT NULL THEN
        EXECUTE format('ALTER TABLE note_meetings DROP CONSTRAINT %I', old_check);
    END IF;
END $$;

ALTER TABLE note_meetings ADD CONSTRAINT note_meetings_meeting_type_detected_check
    CHECK (meeting_type_detected IS NULL OR meeting_type_detected IN
           ('auto', 'client', 'team', 'sales', 'one_on_one', 'interview',
            'podcast_broadcast', 'lecture_webinar', 'voice_memo'));
