-- 0017 down — German rows cannot survive the narrower CHECK; drop them
-- before restoring the uk/en constraint.
DELETE FROM autocomplete_snippets WHERE language = 'de';
ALTER TABLE autocomplete_snippets
    DROP CONSTRAINT IF EXISTS autocomplete_snippets_language_check;
ALTER TABLE autocomplete_snippets
    ADD CONSTRAINT autocomplete_snippets_language_check
        CHECK (language IN ('uk', 'en'));

DELETE FROM autocomplete_phrases WHERE language = 'de';
ALTER TABLE autocomplete_phrases
    DROP CONSTRAINT IF EXISTS autocomplete_phrases_language_check;
ALTER TABLE autocomplete_phrases
    ADD CONSTRAINT autocomplete_phrases_language_check
        CHECK (language IN ('uk', 'en'));

DELETE FROM synonyms WHERE language = 'de';
ALTER TABLE synonyms
    DROP CONSTRAINT IF EXISTS synonyms_language_check;
ALTER TABLE synonyms
    ADD CONSTRAINT synonyms_language_check
        CHECK (language IN ('uk', 'en'));

DELETE FROM templates WHERE language = 'de';
ALTER TABLE templates
    DROP CONSTRAINT IF EXISTS templates_language_check;
ALTER TABLE templates
    ADD CONSTRAINT templates_language_check
        CHECK (language IN ('uk', 'en'));
