-- 0059 — every generated line is a row (Summary Engine v2, Q5).
--
-- `note_generated_items` (0052) held one row per FACT, so a summary
-- sentence, the framing and a topic bullet had no evidence a reader could
-- open. It becomes the line table: those lines are rows too, and each row
-- says what it cites and how sure it is. One table, one route, one client
-- model — the recipient page and the corrections routes read it unchanged
-- (they filter by kind).
--
-- Labels are data: certainty, who holds a position, the name corrections
-- and the resolved dates are columns the client renders, never words
-- added to the note's text.

ALTER TABLE note_generated_items
    ADD COLUMN cites         TEXT[] NOT NULL DEFAULT '{}'
        CHECK (array_length(cites, 1) IS NULL OR array_length(cites, 1) <= 16),
    ADD COLUMN certainty     TEXT
        CHECK (certainty IS NULL OR certainty IN
               ('fact', 'estimate', 'prediction', 'opinion', 'proposal', 'allegation')),
    ADD COLUMN attributed_to TEXT
        CHECK (attributed_to IS NULL OR char_length(attributed_to) <= 60),
    -- [{surface, canonical, source}], at most 8
    ADD COLUMN corrections   JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(corrections) = 'array' AND jsonb_array_length(corrections) <= 8),
    -- [{text, date, time, direction}], at most 8
    ADD COLUMN mentions      JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(mentions) = 'array' AND jsonb_array_length(mentions) <= 8);

-- `kind` had only a length CHECK (0052's inline one, which keeps its
-- generated name `note_generated_items_kind_check`). This adds the
-- vocabulary: every kind the engine emits — the generic set, each family's
-- own, judgements — plus the four line kinds Q5 adds. A test
-- (test_meeting_doc_q5) fails when the engine grows a kind this list lacks.
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

-- A name the engine respelled can be rejected (the line goes back to what
-- was heard) or accepted (it becomes a glossary term).
ALTER TABLE note_item_corrections DROP CONSTRAINT IF EXISTS note_item_corrections_action_check;
ALTER TABLE note_item_corrections ADD CONSTRAINT note_item_corrections_action_check
    CHECK (action IN ('dismiss', 'restore', 'add', 'owner_changed', 'due_changed',
                      'kind_changed', 'correction_rejected', 'correction_accepted'));
ALTER TABLE note_item_corrections DROP CONSTRAINT IF EXISTS note_item_corrections_reason_check;
ALTER TABLE note_item_corrections ADD CONSTRAINT note_item_corrections_reason_check
    CHECK (reason IN ('not_said', 'not_a_decision', 'not_a_task', 'wrong_owner',
                      'wrong_date', 'duplicate', 'not_relevant', 'wrong_name'));
