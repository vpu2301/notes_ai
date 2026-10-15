-- Reverse of 0072. Workspace notifications go with the categories; the 0011
-- CHECKs come back NOT VALID so rows of the four categories 0072 legalised
-- are kept rather than deleted on rollback.
DELETE FROM notifications WHERE category LIKE 'workspace.%';
DELETE FROM notification_preferences WHERE category LIKE 'workspace.%';
ALTER TABLE notifications DROP CONSTRAINT notifications_category_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_category_check
    CHECK (category IN (
        'note.finalized', 'note.amended', 'note.chain_failure', 'note.shared_with_you',
        'dictation.completed', 'transcription.completed', 'transcription.failed',
        'security.mfa_reminder', 'system.digest'
    )) NOT VALID;
ALTER TABLE notification_preferences DROP CONSTRAINT notification_preferences_category_check;
ALTER TABLE notification_preferences ADD CONSTRAINT notification_preferences_category_check
    CHECK (category IN (
        'note.finalized', 'note.amended', 'note.chain_failure', 'note.shared_with_you',
        'dictation.completed', 'transcription.completed', 'transcription.failed',
        'security.mfa_reminder', 'system.digest'
    )) NOT VALID;

ALTER TABLE tenant_memberships DROP COLUMN left_at;
DROP POLICY funnel_reader_select ON tenant_invitations;
DROP TABLE tenant_invitations;
