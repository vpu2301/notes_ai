ALTER TABLE note_generations DROP COLUMN IF EXISTS config_snapshot;
DROP TABLE IF EXISTS note_experiment_reviews;
DROP TABLE IF EXISTS note_experiment_runs;
DROP TABLE IF EXISTS note_experiments;
DROP TABLE IF EXISTS prompt_profile_activations;
DROP TABLE IF EXISTS prompt_profile_bindings;
DROP TABLE IF EXISTS prompt_profile_versions;
DROP FUNCTION IF EXISTS prompt_profile_versions_immutable();
DROP TABLE IF EXISTS prompt_profiles;
