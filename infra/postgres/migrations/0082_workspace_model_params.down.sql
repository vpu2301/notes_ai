ALTER TABLE workspace_model_settings
    DROP COLUMN IF EXISTS model_params_version,
    DROP COLUMN IF EXISTS model_params,
    DROP COLUMN IF EXISTS writing_style;
