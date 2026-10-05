-- Revert 0058: back to the six meeting types of 0051. A recording detected
-- as one of the three new types forgets it (the generation's own stats
-- still say what it was).
UPDATE note_meetings
   SET meeting_type_detected = NULL
 WHERE meeting_type_detected IN ('podcast_broadcast', 'lecture_webinar', 'voice_memo');

ALTER TABLE note_meetings DROP CONSTRAINT IF EXISTS note_meetings_meeting_type_detected_check;

ALTER TABLE note_meetings ADD CONSTRAINT note_meetings_meeting_type_detected_check
    CHECK (meeting_type_detected IS NULL OR meeting_type_detected IN
           ('auto', 'client', 'team', 'sales', 'one_on_one', 'interview'));
