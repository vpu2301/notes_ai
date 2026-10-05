-- Down: titles keep their text; only the record of who wrote them goes.
ALTER TABLE notes
    DROP COLUMN IF EXISTS title_generated_at,
    DROP COLUMN IF EXISTS title_source;
