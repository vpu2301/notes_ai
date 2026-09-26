-- Revert 0065. Rows of the three F3 kinds go; a note detected as a
-- presentation reads as a lecture (the nearest 0058 type).
DELETE FROM note_generated_items WHERE kind IN ('figure', 'introduction', 'next_step');
ALTER TABLE note_generated_items DROP COLUMN IF EXISTS payload;
ALTER TABLE note_generated_items DROP CONSTRAINT IF EXISTS note_generated_items_kind_vocab_check;
ALTER TABLE note_generated_items ADD CONSTRAINT note_generated_items_kind_vocab_check
    CHECK (kind IN (
        'action', 'agenda_item', 'blocker', 'budget_timeline', 'candidate_fact', 'challenge',
        'client_request', 'commitment_ours', 'commitment_theirs', 'competitor_mention',
        'completion', 'concern', 'decision', 'feedback_given', 'feedback_received',
        'growth_topic', 'judgement', 'key_point', 'need', 'next_meeting', 'objection',
        'open_question', 'progress', 'question', 'risk', 'stakeholder', 'status_statement',
        'strength', 'user_point', 'win',
        'summary_sentence', 'framing', 'topic_bullet', 'date'
    ));
UPDATE note_meetings SET meeting_type_detected = 'lecture_webinar'
 WHERE meeting_type_detected = 'presentation_demo';
ALTER TABLE note_meetings DROP CONSTRAINT IF EXISTS note_meetings_meeting_type_detected_check;
ALTER TABLE note_meetings ADD CONSTRAINT note_meetings_meeting_type_detected_check
    CHECK (meeting_type_detected IS NULL OR meeting_type_detected IN
           ('auto', 'client', 'team', 'sales', 'one_on_one', 'interview',
            'podcast_broadcast', 'lecture_webinar', 'voice_memo'));
