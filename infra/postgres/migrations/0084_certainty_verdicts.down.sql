-- A relayed claim folds back into `allegation`, the nearest of the older values.
UPDATE note_generated_items SET certainty = 'allegation'
    WHERE certainty IN ('reported', 'unproven', 'refuted');
ALTER TABLE note_generated_items
    DROP CONSTRAINT note_generated_items_certainty_check,
    ADD CONSTRAINT note_generated_items_certainty_check CHECK (certainty IS NULL OR certainty IN
        ('fact', 'estimate', 'prediction', 'opinion', 'proposal', 'allegation'));
