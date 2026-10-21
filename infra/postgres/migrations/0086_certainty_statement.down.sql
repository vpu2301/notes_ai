-- A statement folds back into `fact`; its holder stays in attributed_to.
UPDATE note_generated_items SET certainty = 'fact' WHERE certainty = 'statement';
ALTER TABLE note_generated_items
    DROP CONSTRAINT note_generated_items_certainty_check,
    ADD CONSTRAINT note_generated_items_certainty_check CHECK (certainty IS NULL OR certainty IN
        ('fact', 'estimate', 'prediction', 'opinion', 'proposal', 'allegation',
         'reported', 'unproven', 'refuted'));
