DROP FUNCTION IF EXISTS public.move_note_to_workspace(uuid, uuid, uuid, text);
DROP FUNCTION IF EXISTS public.can_create_in_workspace(uuid, uuid);
DROP FUNCTION IF EXISTS public.default_visibility_for_note(uuid);

-- 0075's body.
CREATE OR REPLACE FUNCTION public.note_access_for_job(p_job_id uuid, p_sub uuid, p_roles text[])
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

DELETE FROM notifications WHERE category IN ('note.moved', 'workspace.notes_shared');
DELETE FROM notification_preferences WHERE category IN ('note.moved', 'workspace.notes_shared');
ALTER TABLE notifications DROP CONSTRAINT notifications_category_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_category_check
    CHECK (category IN (
        'note.finalized', 'note.amended', 'note.chain_failure', 'note.shared_with_you',
        'note.recipient_responded', 'note.link_status_changed', 'share.reported',
        'dictation.completed', 'transcription.completed', 'transcription.failed',
        'security.mfa_reminder', 'ai.budget_reached', 'system.digest',
        'workspace.invited', 'workspace.invitation_accepted', 'workspace.member_removed',
        'note.commented', 'note.access_changed'
    ));
ALTER TABLE notification_preferences DROP CONSTRAINT notification_preferences_category_check;
ALTER TABLE notification_preferences ADD CONSTRAINT notification_preferences_category_check
    CHECK (category IN (
        'note.finalized', 'note.amended', 'note.chain_failure', 'note.shared_with_you',
        'note.recipient_responded', 'note.link_status_changed', 'share.reported',
        'dictation.completed', 'transcription.completed', 'transcription.failed',
        'security.mfa_reminder', 'ai.budget_reached', 'system.digest',
        'workspace.invited', 'workspace.invitation_accepted', 'workspace.member_removed',
        'note.commented', 'note.access_changed'
    ));
