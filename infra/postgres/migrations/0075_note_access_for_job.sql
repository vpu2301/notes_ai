-- 0075 — Transcript access is decided by the note (W3, ADR-0071) and enforced
-- by the service that holds the transcript. asr-service calls this under its
-- own tenant-scoped connection: NOT SECURITY DEFINER, so RLS on notes,
-- note_meetings, note_collaborators and tenant_memberships applies and a
-- caller from another tenant gets no rows. No row = no note links to the job
-- (upload-only transcription keeps asr-service's own rule). A linked note the
-- caller has no grant on is a row with level NULL and transcript false — never
-- "no row", or a colleague's private transcript would fall back to `asr.read`.
--
-- rank: 4 manage, 3 edit, 2 comment, 1 view. Transcript: edit or above, or
-- any reader once the author turned on `transcript_shared`.
CREATE FUNCTION public.note_access_for_job(p_job_id uuid, p_sub uuid, p_roles text[])
RETURNS TABLE (level text, transcript boolean) LANGUAGE sql STABLE AS $$
  WITH linked AS (
    SELECT n.* FROM notes n
    WHERE n.deleted_at IS NULL AND (n.source_asr_job_id = p_job_id
       OR n.id IN (SELECT note_id FROM note_meetings WHERE asr_job_id = p_job_id))
  ), ranked AS (
    SELECT n.id, n.transcript_shared, GREATEST(
      CASE WHEN p_sub = n.primary_author_id OR p_sub = ANY(n.co_author_ids) THEN 4 END,
      CASE WHEN 'tenant_admin' = ANY(p_roles) THEN 4 END,
      (SELECT array_position(ARRAY['view','comment','edit'], c.role::text)
         FROM note_collaborators c
        WHERE c.note_id = n.id AND c.user_sub = p_sub
          AND EXISTS (SELECT 1 FROM tenant_memberships m
                       WHERE m.tenant_id = n.tenant_id AND m.user_sub = p_sub
                         AND m.status = 'active')),
      CASE WHEN n.visibility = 'workspace' AND 'member' = ANY(p_roles) THEN 3
           WHEN n.visibility = 'workspace' AND 'viewer' = ANY(p_roles) THEN 2 END,
      CASE WHEN 'auditor' = ANY(p_roles) THEN 1 END) AS rank
    FROM linked n)
  SELECT (ARRAY['view','comment','edit','manage'])[rank] AS level,
         (rank IS NOT NULL AND (rank >= 3 OR transcript_shared)) AS transcript
  FROM ranked ORDER BY rank DESC NULLS LAST LIMIT 1
$$;
GRANT EXECUTE ON FUNCTION public.note_access_for_job(uuid, uuid, text[]) TO app_role;

-- The function looks meeting notes up by job; without this it scans note_meetings per call.
CREATE INDEX IF NOT EXISTS note_meetings_asr_job_idx ON note_meetings (asr_job_id)
    WHERE asr_job_id IS NOT NULL;
