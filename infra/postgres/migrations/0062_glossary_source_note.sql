-- 0062 — Sprint I2 T6: where a glossary term came from.
--
-- A term added from a "Remember this?" offer after a speaker rename
-- records the note it was renamed in, so the glossary page can say
-- "added from <note>, by <who>, on <date>" and a person can judge
-- whether it belongs in every recording's vocabulary. NULL for terms
-- typed on the glossary page and for every term before this column.
-- The note may be deleted later; the term stays (SET NULL). Same tenant
-- is checked by the route under RLS before the insert (F-25: no
-- composite tenant key on notes).
ALTER TABLE workspace_glossary
    ADD COLUMN source_note_id UUID REFERENCES notes(id) ON DELETE SET NULL;
