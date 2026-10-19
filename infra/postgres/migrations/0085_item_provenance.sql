-- 0085 — Sprint B4: what a written line is, from the facts it rests on — the speaker's
-- words (`verbatim`), one fact written anew (`paraphrase`) or several facts in one sentence
-- (`composed`). Null for rows written before this sprint; a re-generate fills it. The
-- claims table's rows are a kind of their own (`claim`), so the kind vocabulary grows.

ALTER TABLE note_generated_items
    ADD COLUMN provenance TEXT
        CHECK (provenance IS NULL OR provenance IN ('verbatim', 'paraphrase', 'composed'));

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
        'figure', 'introduction', 'next_step', 'claim'
    ));
