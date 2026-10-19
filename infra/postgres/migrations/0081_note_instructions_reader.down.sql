DROP POLICY IF EXISTS funnel_reader_select ON workspace_note_instructions;
REVOKE SELECT (tenant_id, scope, version, compile_status, compile_error_kind, compiler_version,
               backend, created_at, updated_at)
    ON workspace_note_instructions FROM funnel_reader;
