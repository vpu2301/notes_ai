DELETE FROM note_generated_items WHERE kind = 'claim';
ALTER TABLE note_generated_items DROP CONSTRAINT note_generated_items_kind_vocab_check;
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
ALTER TABLE note_generated_items DROP COLUMN IF EXISTS provenance;
