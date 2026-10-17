-- Reverse of 0074. Rows of the two categories go first; 0072's CHECKs come
-- back NOT VALID, like 0072's own down.
DELETE FROM notifications WHERE category IN ('note.commented', 'note.access_changed');
DELETE FROM notification_preferences WHERE category IN ('note.commented', 'note.access_changed');
ALTER TABLE notifications DROP CONSTRAINT notifications_category_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_category_check
    CHECK (category IN (
        'note.finalized', 'note.amended', 'note.chain_failure', 'note.shared_with_you',
        'note.recipient_responded', 'note.link_status_changed', 'share.reported',
        'dictation.completed', 'transcription.completed', 'transcription.failed',
        'security.mfa_reminder', 'ai.budget_reached', 'system.digest',
        'workspace.invited', 'workspace.invitation_accepted', 'workspace.member_removed'
    )) NOT VALID;
ALTER TABLE notification_preferences DROP CONSTRAINT notification_preferences_category_check;
ALTER TABLE notification_preferences ADD CONSTRAINT notification_preferences_category_check
    CHECK (category IN (
        'note.finalized', 'note.amended', 'note.chain_failure', 'note.shared_with_you',
        'note.recipient_responded', 'note.link_status_changed', 'share.reported',
        'dictation.completed', 'transcription.completed', 'transcription.failed',
        'security.mfa_reminder', 'ai.budget_reached', 'system.digest',
        'workspace.invited', 'workspace.invitation_accepted', 'workspace.member_removed'
    )) NOT VALID;

DROP TABLE note_comments;
