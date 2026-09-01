DROP FUNCTION IF EXISTS autocomplete_bump_phrase_counters(uuid, bigint, bigint, timestamptz);
DROP FUNCTION IF EXISTS autocomplete_drop_telemetry_partition(date);
DROP FUNCTION IF EXISTS autocomplete_create_telemetry_partition(date, date);
DROP TABLE IF EXISTS autocomplete_rollup_progress;
DROP TABLE IF EXISTS autocomplete_telemetry;  -- drops all partitions with it
DROP TABLE IF EXISTS autocomplete_snippets;
DROP TABLE IF EXISTS autocomplete_phrases;
DROP TYPE IF EXISTS autocomplete_source;
