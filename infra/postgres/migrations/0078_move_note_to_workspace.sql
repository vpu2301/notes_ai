-- 0078 — Move a note to another workspace (W5). One SECURITY DEFINER function
-- re-parents the note and every row that belongs to it, re-checking every
-- permission itself (the caller's claims are never trusted for the target).
-- The objects (audio, transcripts) are re-encrypted afterwards by note-service's
-- `note.rehome_media` job, queued by this function in the same transaction; until then `notes.media_state = 'rehoming'` and the
-- transcript is closed for everyone (`note_access_for_job` below).
--
-- Every table with a `note_id` that references notes(id), and every table that
-- hangs off the note's transcription job, is named here;
-- `scripts/ci/check-note-move-covers-all-tables.py` fails when a new one is not.
-- Left alone on purpose: note_versions (no tenant_id, RLS through the note),
-- workspace_glossary.source_note_id (an origin pointer), model_usage (billing
-- history stays where it was spent), audit.note_chain_failures (ops history),
-- tenant_invitations.note_id (auth-service's; an open invitation to the old
-- workspace grants nothing once the note is gone from it).

-- The family rule of `note_service.domain.visibility.default_for_note` in a team
-- workspace (the caller handles personal): person-centred notes stay private.
-- Unit-tested against the Python rule; keep the three lists equal to
-- SENSITIVE_MEETING_TYPES / SENSITIVE_DETECTED / SENSITIVE_TEMPLATE_PREFIXES.
CREATE FUNCTION public.default_visibility_for_note(p_note uuid)
RETURNS note_visibility
LANGUAGE sql STABLE SET search_path = public AS $$
    SELECT CASE WHEN
        COALESCE(m.meeting_type, '') IN ('interview', 'memo', 'one_on_one')
        OR COALESCE(m.meeting_type_detected, '') IN ('interview', 'one_on_one', 'voice_memo')
        OR starts_with(lower(COALESCE(t.code, '')), 'interview_debrief')
        OR starts_with(lower(COALESCE(t.code, '')), 'one_on_one')
        OR starts_with(lower(COALESCE(t.code, '')), 'voice_memo')
    THEN 'private'::note_visibility ELSE 'workspace'::note_visibility END
    FROM notes n
    LEFT JOIN note_meetings m ON m.note_id = n.id
    LEFT JOIN templates t ON t.id = n.template_id
    WHERE n.id = p_note
$$;
REVOKE ALL ON FUNCTION public.default_visibility_for_note(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.default_visibility_for_note(uuid) TO app_role;

-- app_role cannot read another workspace's memberships; copy asks here.
CREATE FUNCTION public.can_create_in_workspace(p_tenant uuid, p_sub uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT EXISTS (
        SELECT 1 FROM tenant_memberships m JOIN tenants t ON t.id = m.tenant_id
         WHERE m.tenant_id = p_tenant AND m.user_sub = p_sub AND m.status = 'active'
           AND m.role IN ('owner', 'admin', 'member') AND t.status = 'active'
           AND (t.kind <> 'personal' OR m.role = 'owner')
    )
$$;
REVOKE ALL ON FUNCTION public.can_create_in_workspace(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.can_create_in_workspace(uuid, uuid) TO app_role;

-- Errors are raised with the code as the message; note-service maps the message.
CREATE FUNCTION public.move_note_to_workspace(
    p_note uuid, p_to_tenant uuid, p_actor uuid, p_new_code text)
RETURNS TABLE (moved_media boolean, job_id uuid, audio_ids uuid[])
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_from uuid := current_setting('app.tenant_id', true)::uuid;
    n record; tgt record; m record; j record; d record;
    v_job uuid; v_audio uuid[] := '{}'; v_collabs uuid[];
    v_has_job boolean := false; v_has_session boolean := false;
    v_visibility note_visibility; v_source text;
BEGIN
    SELECT * INTO n FROM notes
     WHERE id = p_note AND tenant_id = v_from AND deleted_at IS NULL FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'note_not_found' USING ERRCODE = 'P0002'; END IF;
    IF v_from = p_to_tenant THEN RAISE EXCEPTION 'same_workspace' USING ERRCODE = 'P0003'; END IF;
    IF NOT public.can_manage_note(v_from, p_note, p_actor) THEN
        RAISE EXCEPTION 'insufficient_role' USING ERRCODE = 'P0004'; END IF;
    -- Membership first, status second: a workspace the actor is not in answers
    -- not_a_member whether or not it exists (no existence oracle).
    SELECT tm.role INTO m FROM tenant_memberships tm
     WHERE tm.tenant_id = p_to_tenant AND tm.user_sub = p_actor AND tm.status = 'active'
       AND tm.role IN ('owner', 'admin', 'member');
    IF NOT FOUND THEN RAISE EXCEPTION 'not_a_member' USING ERRCODE = 'P0006'; END IF;
    SELECT t.kind, t.status INTO tgt FROM tenants t WHERE t.id = p_to_tenant;
    IF NOT FOUND OR tgt.status <> 'active' THEN
        RAISE EXCEPTION 'target_unavailable' USING ERRCODE = 'P0005'; END IF;
    IF tgt.kind = 'personal' AND m.role <> 'owner' THEN
        RAISE EXCEPTION 'not_a_member' USING ERRCODE = 'P0006'; END IF;
    -- The caller draws the code from the target's sequence only once it may create there.
    IF COALESCE(p_new_code, '') = '' THEN
        RAISE EXCEPTION 'invalid_code' USING ERRCODE = '22023'; END IF;

    -- A queued generation would find nothing here and its result would be lost.
    IF EXISTS (SELECT 1 FROM jobs
                WHERE tenant_id = v_from AND kind = 'note.generate'
                  AND payload->>'note_id' = p_note::text
                  AND status IN ('queued', 'running', 'waiting_on_model')) THEN
        RAISE EXCEPTION 'generation_in_progress' USING ERRCODE = 'P0008';
    END IF;

    -- The last move's media is still on its way; moving again would race that job.
    IF n.media_state = 'rehoming' THEN
        RAISE EXCEPTION 'media_in_progress' USING ERRCODE = 'P0009';
    END IF;

    -- A workspace's own template is unreadable from another workspace (templates RLS).
    IF EXISTS (SELECT 1 FROM templates t WHERE t.id = n.template_id AND t.tenant_id IS NOT NULL) THEN
        RAISE EXCEPTION 'custom_template' USING ERRCODE = 'P0010';
    END IF;

    -- Media: the job linked to this note, refused if any other note here still points at it.
    v_job := COALESCE(n.source_asr_job_id,
                      (SELECT nm.asr_job_id FROM note_meetings nm WHERE nm.note_id = p_note));
    IF v_job IS NOT NULL AND EXISTS (
        SELECT 1 FROM notes o WHERE o.tenant_id = v_from AND o.id <> p_note
           AND (o.source_asr_job_id = v_job
                OR o.id IN (SELECT nm.note_id FROM note_meetings nm WHERE nm.asr_job_id = v_job))) THEN
        RAISE EXCEPTION 'media_shared' USING ERRCODE = 'P0007';
    END IF;
    IF v_job IS NOT NULL THEN
        SELECT tj.audio_id, tj.status, tj.diarization_status INTO j
          FROM transcription_jobs tj WHERE tj.id = v_job AND tj.tenant_id = v_from;
        v_has_job := FOUND;
        -- The worker would write the result under the old workspace.
        IF v_has_job AND (j.status IN ('queued', 'running')
                      OR j.diarization_status IN ('queued', 'running')) THEN
            RAISE EXCEPTION 'media_in_progress' USING ERRCODE = 'P0009';
        END IF;
    END IF;
    IF n.source_session_id IS NOT NULL THEN
        SELECT ds.audio_file_id, ds.status INTO d
          FROM dictation_sessions ds WHERE ds.id = n.source_session_id AND ds.tenant_id = v_from;
        v_has_session := FOUND;
        IF v_has_session AND d.status IN ('creating', 'active', 'paused', 'reconnecting') THEN
            RAISE EXCEPTION 'media_in_progress' USING ERRCODE = 'P0009';
        END IF;
    END IF;

    -- The audience the note had here, captured before collaborators are pruned (the stub).
    SELECT COALESCE(array_agg(c.user_sub), '{}') INTO v_collabs
      FROM note_collaborators c WHERE c.note_id = p_note;

    -- Visibility: Personal is private; the author's lock travels; else the family default.
    IF tgt.kind = 'personal' THEN
        v_visibility := 'private'; v_source := 'default';
    ELSIF n.visibility = 'private' AND n.visibility_source = 'author' THEN
        v_visibility := 'private'; v_source := 'author';
    ELSE
        v_visibility := public.default_visibility_for_note(p_note); v_source := 'default';
    END IF;

    UPDATE notes SET tenant_id = p_to_tenant, code = p_new_code, visibility = v_visibility,
                     visibility_source = v_source, updated_at = now()
     WHERE id = p_note;
    UPDATE note_meetings         SET tenant_id = p_to_tenant WHERE note_id = p_note;
    UPDATE note_generations      SET tenant_id = p_to_tenant WHERE note_id = p_note;
    UPDATE note_generated_items  SET tenant_id = p_to_tenant WHERE note_id = p_note;
    UPDATE note_item_corrections SET tenant_id = p_to_tenant WHERE note_id = p_note;
    UPDATE note_action_items     SET tenant_id = p_to_tenant WHERE note_id = p_note;
    UPDATE note_user_line_times  SET tenant_id = p_to_tenant WHERE note_id = p_note;
    -- A series does not span workspaces: the moved note starts its own there.
    UPDATE note_meetings SET previous_note_id = NULL
     WHERE note_id = p_note OR (tenant_id = v_from AND previous_note_id = p_note);
    DELETE FROM note_carried_items WHERE note_id = p_note OR from_note_id = p_note;
    DELETE FROM note_space_items WHERE note_id = p_note;          -- spaces are per workspace+user
    DELETE FROM note_collaborators c WHERE c.note_id = p_note AND NOT EXISTS (
        SELECT 1 FROM tenant_memberships tm WHERE tm.tenant_id = p_to_tenant
           AND tm.user_sub = c.user_sub AND tm.status = 'active');
    UPDATE note_collaborators    SET tenant_id = p_to_tenant WHERE note_id = p_note;
    UPDATE note_comments         SET tenant_id = p_to_tenant WHERE note_id = p_note;
    UPDATE note_share_links      SET tenant_id = p_to_tenant WHERE note_id = p_note;
    UPDATE share_link_responses  SET tenant_id = p_to_tenant WHERE note_id = p_note;
    UPDATE share_abuse_reports   SET tenant_id = p_to_tenant WHERE note_id = p_note;
    UPDATE share_link_otps       SET tenant_id = p_to_tenant
     WHERE link_id IN (SELECT l.id FROM note_share_links l WHERE l.note_id = p_note);

    IF v_has_job THEN
        UPDATE transcription_jobs          SET tenant_id = p_to_tenant WHERE id = v_job;
        UPDATE transcription_speaker_edits e SET tenant_id = p_to_tenant WHERE e.job_id = v_job;
        UPDATE transcript_corrections c      SET tenant_id = p_to_tenant WHERE c.job_id = v_job;
        UPDATE audio_files SET tenant_id = p_to_tenant WHERE id = j.audio_id AND tenant_id = v_from;
        v_audio := v_audio || j.audio_id;
    ELSE
        v_job := NULL;
    END IF;
    IF v_has_session THEN
        UPDATE dictation_sessions SET tenant_id = p_to_tenant
         WHERE id = n.source_session_id AND tenant_id = v_from;
        IF d.audio_file_id IS NOT NULL THEN
            UPDATE audio_files SET tenant_id = p_to_tenant
             WHERE id = d.audio_file_id AND tenant_id = v_from;
            v_audio := v_audio || d.audio_file_id;
        END IF;
    END IF;
    IF v_job IS NOT NULL OR cardinality(v_audio) > 0 THEN
        UPDATE notes SET media_state = 'rehoming' WHERE id = p_note;
        -- The re-home job, in the same transaction: a move never ends up rehoming with no job.
        -- Under the TARGET workspace; ids only (job rows reach operators and metrics).
        INSERT INTO jobs (tenant_id, kind, payload, max_attempts, idempotency_key)
        VALUES (p_to_tenant, 'note.rehome_media',
                jsonb_build_object(
                    'note_id', p_note, 'from_tenant_id', v_from, 'job_id', v_job,
                    'audio_ids', to_jsonb(v_audio),
                    'session_id', CASE WHEN v_has_session THEN n.source_session_id END),
                8, 'rehome:' || p_note || ':' || gen_random_uuid());
    END IF;

    INSERT INTO note_relocations (note_id, tenant_id, to_tenant_id, moved_by, old_code, new_code,
                                  was_workspace_visible, author_team, collaborator_subs)
    VALUES (p_note, v_from, p_to_tenant, p_actor, n.code, p_new_code,
            n.visibility = 'workspace', ARRAY[n.primary_author_id] || n.co_author_ids, v_collabs)
    ON CONFLICT (tenant_id, note_id) DO UPDATE
       SET to_tenant_id = EXCLUDED.to_tenant_id, moved_by = EXCLUDED.moved_by,
           moved_at = now(), old_code = EXCLUDED.old_code, new_code = EXCLUDED.new_code,
           was_workspace_visible = EXCLUDED.was_workspace_visible,
           author_team = EXCLUDED.author_team, collaborator_subs = EXCLUDED.collaborator_subs;
    -- Moving back clears the stub that pointed here.
    DELETE FROM note_relocations r WHERE r.note_id = p_note AND r.tenant_id = p_to_tenant;

    RETURN QUERY SELECT (v_job IS NOT NULL OR cardinality(v_audio) > 0), v_job, v_audio;
END $$;
REVOKE ALL ON FUNCTION public.move_note_to_workspace(uuid, uuid, uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.move_note_to_workspace(uuid, uuid, uuid, text) TO app_role;

-- 0075's rule, plus: nobody reads the transcript of a moved note until its media is home.
CREATE OR REPLACE FUNCTION public.note_access_for_job(p_job_id uuid, p_sub uuid, p_roles text[])
RETURNS TABLE (level text, transcript boolean) LANGUAGE sql STABLE AS $$
  WITH linked AS (
    SELECT n.* FROM notes n
    WHERE n.deleted_at IS NULL AND (n.source_asr_job_id = p_job_id
       OR n.id IN (SELECT note_id FROM note_meetings WHERE asr_job_id = p_job_id))
  ), ranked AS (
    SELECT n.id, n.transcript_shared, n.media_state, GREATEST(
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
         (rank IS NOT NULL AND (rank >= 3 OR transcript_shared) AND media_state = 'ready')
             AS transcript
  FROM ranked ORDER BY rank DESC NULLS LAST LIMIT 1
$$;

-- Two notification categories: a note someone else moved, and the backfill notice.
ALTER TABLE notifications DROP CONSTRAINT notifications_category_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_category_check
    CHECK (category IN (
        'note.finalized', 'note.amended', 'note.chain_failure', 'note.shared_with_you',
        'note.recipient_responded', 'note.link_status_changed', 'share.reported',
        'dictation.completed', 'transcription.completed', 'transcription.failed',
        'security.mfa_reminder', 'ai.budget_reached', 'system.digest',
        'workspace.invited', 'workspace.invitation_accepted', 'workspace.member_removed',
        'note.commented', 'note.access_changed',
        'note.moved', 'workspace.notes_shared'
    ));
ALTER TABLE notification_preferences DROP CONSTRAINT notification_preferences_category_check;
ALTER TABLE notification_preferences ADD CONSTRAINT notification_preferences_category_check
    CHECK (category IN (
        'note.finalized', 'note.amended', 'note.chain_failure', 'note.shared_with_you',
        'note.recipient_responded', 'note.link_status_changed', 'share.reported',
        'dictation.completed', 'transcription.completed', 'transcription.failed',
        'security.mfa_reminder', 'ai.budget_reached', 'system.digest',
        'workspace.invited', 'workspace.invitation_accepted', 'workspace.member_removed',
        'note.commented', 'note.access_changed',
        'note.moved', 'workspace.notes_shared'
    ));
