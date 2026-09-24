-- Revert 0059. Line rows (summary sentences, framing, topic bullets,
-- dates) go; fact rows keep what 0052 had. Corrections with the two new
-- actions or the new reason are removed with them.
DELETE FROM note_generated_items
 WHERE kind IN ('summary_sentence', 'framing', 'topic_bullet', 'date');
ALTER TABLE note_generated_items DROP CONSTRAINT IF EXISTS note_generated_items_kind_vocab_check;
ALTER TABLE note_generated_items
    DROP COLUMN IF EXISTS cites,
    DROP COLUMN IF EXISTS certainty,
    DROP COLUMN IF EXISTS attributed_to,
    DROP COLUMN IF EXISTS corrections,
    DROP COLUMN IF EXISTS mentions;

DELETE FROM note_item_corrections
 WHERE action IN ('correction_rejected', 'correction_accepted') OR reason = 'wrong_name';
ALTER TABLE note_item_corrections DROP CONSTRAINT IF EXISTS note_item_corrections_action_check;
ALTER TABLE note_item_corrections ADD CONSTRAINT note_item_corrections_action_check
    CHECK (action IN ('dismiss', 'restore', 'add', 'owner_changed', 'due_changed', 'kind_changed'));
ALTER TABLE note_item_corrections DROP CONSTRAINT IF EXISTS note_item_corrections_reason_check;
ALTER TABLE note_item_corrections ADD CONSTRAINT note_item_corrections_reason_check
    CHECK (reason IN ('not_said', 'not_a_decision', 'not_a_task', 'wrong_owner',
                      'wrong_date', 'duplicate', 'not_relevant'));
