-- 0084 — Sprint B2 T4: the certainty of a claim a speaker relays joins the closed
-- vocabulary of note_generated_items.certainty: `reported` (only relayed), `unproven`
-- (the speaker calls it unsubstantiated) and `refuted` (the speaker calls it disproven).
-- Labels are data the client renders; the note's text carries the verdict by code.

ALTER TABLE note_generated_items
    DROP CONSTRAINT note_generated_items_certainty_check,
    ADD CONSTRAINT note_generated_items_certainty_check CHECK (certainty IS NULL OR certainty IN
        ('fact', 'estimate', 'prediction', 'opinion', 'proposal', 'allegation',
         'reported', 'unproven', 'refuted'));
