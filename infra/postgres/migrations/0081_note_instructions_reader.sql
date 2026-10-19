-- 0081 — the "Note instructions" row of the admin Meeting quality dashboard (Sprint N5),
-- read as funnel_reader. Metadata only, extending 0067:
--     workspace_note_instructions  tenant_id, scope, version, compile_status,
--                                  compile_error_kind, compiler_version, backend,
--                                  created_at, updated_at
--                                  NOT text, profile, profile_hash, updated_by
-- The tenant policies are TO app_role (0080), so a permissive SELECT policy for
-- funnel_reader is enough, as for transcript_corrections in 0067.

GRANT SELECT (tenant_id, scope, version, compile_status, compile_error_kind, compiler_version,
              backend, created_at, updated_at)
    ON workspace_note_instructions TO funnel_reader;

CREATE POLICY funnel_reader_select ON workspace_note_instructions
    FOR SELECT TO funnel_reader USING (true);
