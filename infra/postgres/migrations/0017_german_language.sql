-- 0017 — German joins the note-side language vocabulary.
--
-- Batch ASR (0015) and the NLP post-processor already speak `de`; a
-- German meeting was transcribed correctly and then landed under the
-- English template because the note-side tables only allowed `uk`/`en`.
-- Widen every note-side language CHECK so German templates, synonym
-- groups and autocomplete entries can be stored. The template catalogue
-- itself ships as seed files (infra/seeds/templates/*_de.json).

ALTER TABLE templates
    DROP CONSTRAINT IF EXISTS templates_language_check;
ALTER TABLE templates
    ADD CONSTRAINT templates_language_check
        CHECK (language IN ('uk', 'en', 'de'));

ALTER TABLE synonyms
    DROP CONSTRAINT IF EXISTS synonyms_language_check;
ALTER TABLE synonyms
    ADD CONSTRAINT synonyms_language_check
        CHECK (language IN ('uk', 'en', 'de'));

ALTER TABLE autocomplete_phrases
    DROP CONSTRAINT IF EXISTS autocomplete_phrases_language_check;
ALTER TABLE autocomplete_phrases
    ADD CONSTRAINT autocomplete_phrases_language_check
        CHECK (language IN ('uk', 'en', 'de'));

ALTER TABLE autocomplete_snippets
    DROP CONSTRAINT IF EXISTS autocomplete_snippets_language_check;
ALTER TABLE autocomplete_snippets
    ADD CONSTRAINT autocomplete_snippets_language_check
        CHECK (language IN ('uk', 'en', 'de'));
