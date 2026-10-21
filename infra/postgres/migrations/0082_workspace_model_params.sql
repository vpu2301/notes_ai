-- 0082 — Sprint N0: the writing style and the model parameters a workspace sets by hand
-- (Settings → Data & AI → Note writing). The order calls this 0079; 0079–0081 were taken
-- by S3 (prompt profiles), N1 (note instructions) and N5 (the dashboard grant).
-- No backfill: the defaults are today's behaviour. Same table, so RLS is unchanged.

ALTER TABLE workspace_model_settings
    ADD COLUMN writing_style TEXT NOT NULL DEFAULT 'business'
        CHECK (writing_style IN ('business', 'formal', 'informal', 'academic')),
    ADD COLUMN model_params JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(model_params) = 'object'),
    ADD COLUMN model_params_version INTEGER NOT NULL DEFAULT 0
        CHECK (model_params_version >= 0);
