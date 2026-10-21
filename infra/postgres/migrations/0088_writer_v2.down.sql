REVOKE DELETE ON note_generated_items FROM app_role;
ALTER TABLE note_generations DROP CONSTRAINT IF EXISTS note_generations_step_check;
ALTER TABLE note_generations ADD CONSTRAINT note_generations_step_check
    CHECK (step IS NULL OR step IN ('extract', 'write_items', 'reduce', 'write_doc'));
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
        'figure', 'introduction', 'next_step', 'claim'
    ));
ALTER TABLE note_generated_items
    DROP COLUMN IF EXISTS cite_nearest,
    DROP COLUMN IF EXISTS table_row,
    DROP COLUMN IF EXISTS position;
ALTER TABLE note_generations DROP COLUMN IF EXISTS text;
