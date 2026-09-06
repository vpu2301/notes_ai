-- Reverse of 0028: point the foreign keys back at `users`.
--
-- Safe only while `users` still holds every referenced row — which it
-- does, because B2 deliberately stops short of dropping it. Once a later
-- sprint drops `users`, this rollback stops being possible and the
-- forward migration becomes one-way.

ALTER TABLE auth_mail_outbox DROP CONSTRAINT auth_mail_outbox_subject_sub_fkey;
ALTER TABLE auth_mail_outbox ADD CONSTRAINT auth_mail_outbox_subject_sub_fkey
    FOREIGN KEY (subject_sub) REFERENCES users(sub) ON DELETE CASCADE NOT VALID;
ALTER TABLE auth_mail_outbox VALIDATE CONSTRAINT auth_mail_outbox_subject_sub_fkey;

ALTER TABLE auth_password_events DROP CONSTRAINT auth_password_events_subject_sub_fkey;
ALTER TABLE auth_password_events ADD CONSTRAINT auth_password_events_subject_sub_fkey
    FOREIGN KEY (subject_sub) REFERENCES users(sub) ON DELETE CASCADE NOT VALID;
ALTER TABLE auth_password_events VALIDATE CONSTRAINT auth_password_events_subject_sub_fkey;

ALTER TABLE auth_password_reset_tokens DROP CONSTRAINT auth_password_reset_tokens_subject_sub_fkey;
ALTER TABLE auth_password_reset_tokens ADD CONSTRAINT auth_password_reset_tokens_subject_sub_fkey
    FOREIGN KEY (subject_sub) REFERENCES users(sub) ON DELETE CASCADE NOT VALID;
ALTER TABLE auth_password_reset_tokens VALIDATE CONSTRAINT auth_password_reset_tokens_subject_sub_fkey;

ALTER TABLE autocomplete_phrases DROP CONSTRAINT autocomplete_phrases_owner_user_id_fkey;
ALTER TABLE autocomplete_phrases ADD CONSTRAINT autocomplete_phrases_owner_user_id_fkey
    FOREIGN KEY (owner_user_id) REFERENCES users(sub) ON DELETE CASCADE NOT VALID;
ALTER TABLE autocomplete_phrases VALIDATE CONSTRAINT autocomplete_phrases_owner_user_id_fkey;

ALTER TABLE autocomplete_snippets DROP CONSTRAINT autocomplete_snippets_owner_user_id_fkey;
ALTER TABLE autocomplete_snippets ADD CONSTRAINT autocomplete_snippets_owner_user_id_fkey
    FOREIGN KEY (owner_user_id) REFERENCES users(sub) ON DELETE CASCADE NOT VALID;
ALTER TABLE autocomplete_snippets VALIDATE CONSTRAINT autocomplete_snippets_owner_user_id_fkey;

ALTER TABLE mfa_reminders DROP CONSTRAINT mfa_reminders_requested_by_fkey;
ALTER TABLE mfa_reminders ADD CONSTRAINT mfa_reminders_requested_by_fkey
    FOREIGN KEY (requested_by) REFERENCES users(sub) ON DELETE SET NULL NOT VALID;
ALTER TABLE mfa_reminders VALIDATE CONSTRAINT mfa_reminders_requested_by_fkey;

ALTER TABLE mfa_reminders DROP CONSTRAINT mfa_reminders_subject_sub_fkey;
ALTER TABLE mfa_reminders ADD CONSTRAINT mfa_reminders_subject_sub_fkey
    FOREIGN KEY (subject_sub) REFERENCES users(sub) ON DELETE CASCADE NOT VALID;
ALTER TABLE mfa_reminders VALIDATE CONSTRAINT mfa_reminders_subject_sub_fkey;

ALTER TABLE notes DROP CONSTRAINT notes_primary_author_id_fkey;
ALTER TABLE notes ADD CONSTRAINT notes_primary_author_id_fkey
    FOREIGN KEY (primary_author_id) REFERENCES users(sub) ON DELETE RESTRICT NOT VALID;
ALTER TABLE notes VALIDATE CONSTRAINT notes_primary_author_id_fkey;

ALTER TABLE note_versions DROP CONSTRAINT note_versions_created_by_fkey;
ALTER TABLE note_versions ADD CONSTRAINT note_versions_created_by_fkey
    FOREIGN KEY (created_by) REFERENCES users(sub) ON DELETE RESTRICT NOT VALID;
ALTER TABLE note_versions VALIDATE CONSTRAINT note_versions_created_by_fkey;

ALTER TABLE notification_digest_progress DROP CONSTRAINT notification_digest_progress_user_id_fkey;
ALTER TABLE notification_digest_progress ADD CONSTRAINT notification_digest_progress_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(sub) ON DELETE CASCADE NOT VALID;
ALTER TABLE notification_digest_progress VALIDATE CONSTRAINT notification_digest_progress_user_id_fkey;

ALTER TABLE notification_preferences DROP CONSTRAINT notification_preferences_user_id_fkey;
ALTER TABLE notification_preferences ADD CONSTRAINT notification_preferences_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(sub) ON DELETE CASCADE NOT VALID;
ALTER TABLE notification_preferences VALIDATE CONSTRAINT notification_preferences_user_id_fkey;

ALTER TABLE notifications DROP CONSTRAINT notifications_recipient_user_id_fkey;
ALTER TABLE notifications ADD CONSTRAINT notifications_recipient_user_id_fkey
    FOREIGN KEY (recipient_user_id) REFERENCES users(sub) ON DELETE CASCADE NOT VALID;
ALTER TABLE notifications VALIDATE CONSTRAINT notifications_recipient_user_id_fkey;

ALTER TABLE notification_user_settings DROP CONSTRAINT notification_user_settings_user_id_fkey;
ALTER TABLE notification_user_settings ADD CONSTRAINT notification_user_settings_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(sub) ON DELETE CASCADE NOT VALID;
ALTER TABLE notification_user_settings VALIDATE CONSTRAINT notification_user_settings_user_id_fkey;
