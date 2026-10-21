-- 0086 — Sprint A1: `statement` — what a named participant, official or organisation states,
-- warns or assesses in their own voice — joins the closed vocabulary of
-- note_generated_items.certainty. Not unsure; it carries its holder in attributed_to.
-- Old rows keep their values; no backfill.

ALTER TABLE note_generated_items
    DROP CONSTRAINT note_generated_items_certainty_check,
    ADD CONSTRAINT note_generated_items_certainty_check CHECK (certainty IS NULL OR certainty IN
        ('fact', 'estimate', 'prediction', 'opinion', 'proposal', 'allegation',
         'reported', 'unproven', 'refuted', 'statement'));
