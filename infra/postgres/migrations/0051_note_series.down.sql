DROP TABLE IF EXISTS note_carried_items;
ALTER TABLE note_meetings
    DROP COLUMN IF EXISTS detected_by,
    DROP COLUMN IF EXISTS meeting_type_detected,
    DROP COLUMN IF EXISTS previous_note_id,
    DROP COLUMN IF EXISTS series_source,
    DROP COLUMN IF EXISTS series_key;
