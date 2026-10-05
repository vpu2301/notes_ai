DROP FUNCTION IF EXISTS notes_quality_corrections_offered();
DROP FUNCTION IF EXISTS notes_quality_shares();
DROP FUNCTION IF EXISTS notes_quality_kept_lines();
DROP FUNCTION IF EXISTS notes_quality_bare(TEXT);

DROP POLICY IF EXISTS funnel_reader_select ON note_meetings;
DROP POLICY IF EXISTS funnel_reader_select ON note_item_corrections;
DROP POLICY IF EXISTS funnel_reader_select ON note_generated_items;
DROP POLICY IF EXISTS funnel_reader_select ON note_generations;

REVOKE SELECT ON note_meetings, note_item_corrections, note_generated_items, note_generations
    FROM funnel_reader;
