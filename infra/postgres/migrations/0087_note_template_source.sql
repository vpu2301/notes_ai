-- 0087 — Task 4: how a note got its template. `user` = a person chose it (the request named
-- a template id); `auto` = the matcher scored the transcript; `fallback` = the general
-- template because nothing scored. NULL (older rows) counts as not a person's choice:
-- the generation job then classifies the recording instead of trusting the template.

ALTER TABLE notes
    ADD COLUMN template_source text
        CHECK (template_source IS NULL OR template_source IN ('user', 'auto', 'fallback'));
