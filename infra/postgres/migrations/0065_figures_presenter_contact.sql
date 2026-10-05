-- 0065 — Sprint F3: figures, a presenter, a call to action.
--
-- * `figure`, `introduction` and `next_step` join the line-row kinds. A
--   figure row carries its verified payload — {name, value, unit,
--   qualifier}, every word checked against the quote — in `payload`, so a
--   table cell has a source and a client can draw the value without parsing
--   the line. Nullable: every other row has none.
-- * `presentation_demo` joins the recording types a note may be detected
--   as (one person demonstrating a product, a place or an object).
-- Tenant data under the existing RLS; no backfill.
ALTER TABLE note_generated_items
    ADD COLUMN payload JSONB
        CHECK (payload IS NULL OR (jsonb_typeof(payload) = 'object' AND pg_column_size(payload) <= 2048));

ALTER TABLE note_generated_items DROP CONSTRAINT IF EXISTS note_generated_items_kind_vocab_check;
ALTER TABLE note_generated_items ADD CONSTRAINT note_generated_items_kind_vocab_check
    CHECK (kind IN (
        'action', 'agenda_item', 'blocker', 'budget_timeline', 'candidate_fact', 'challenge',
        'client_request', 'commitment_ours', 'commitment_theirs', 'competitor_mention',
        'completion', 'concern', 'decision', 'feedback_given', 'feedback_received',
        'growth_topic', 'judgement', 'key_point', 'need', 'next_meeting', 'objection',
        'open_question', 'progress', 'question', 'risk', 'stakeholder', 'status_statement',
        'strength', 'user_point', 'win',
        'summary_sentence', 'framing', 'topic_bullet', 'date',
        'figure', 'introduction', 'next_step'
    ));

ALTER TABLE note_meetings DROP CONSTRAINT IF EXISTS note_meetings_meeting_type_detected_check;
ALTER TABLE note_meetings ADD CONSTRAINT note_meetings_meeting_type_detected_check
    CHECK (meeting_type_detected IS NULL OR meeting_type_detected IN
           ('auto', 'client', 'team', 'sales', 'one_on_one', 'interview',
            'podcast_broadcast', 'lecture_webinar', 'voice_memo', 'presentation_demo'));
