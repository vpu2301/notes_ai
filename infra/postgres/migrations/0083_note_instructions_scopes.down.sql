DROP TABLE IF EXISTS note_instructions;
DELETE FROM workspace_note_instructions WHERE scope <> 'workspace';
UPDATE workspace_note_instructions SET compile_status = 'failed' WHERE compile_status = 'stale';
ALTER TABLE workspace_note_instructions
    DROP COLUMN IF EXISTS base_versions,
    DROP CONSTRAINT workspace_note_instructions_compile_status_check,
    ADD CONSTRAINT workspace_note_instructions_compile_status_check
        CHECK (compile_status IN ('compiled', 'failed')),
    DROP CONSTRAINT workspace_note_instructions_scope_check,
    ADD CONSTRAINT workspace_note_instructions_scope_check CHECK (scope IN ('workspace'));
