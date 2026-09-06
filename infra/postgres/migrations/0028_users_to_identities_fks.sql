-- 0028 — IDX-B2 step 2: re-point every foreign key from `users` to
-- `identities`.
--
-- A constraint swap, not a data migration: `identities.id` holds the same
-- UUIDs `users.sub` did (migration 0027 backfilled them 1:1), so every
-- value already sitting in a referencing column is already correct. No
-- row is read, written or moved.
--
-- The statements below were GENERATED from `pg_constraint`, not typed by
-- hand, because the inventory in the sprint pack was wrong: it lists six
-- foreign keys and the live catalogue has thirteen. The seven it misses
-- were added by later migrations — four in notification-service's tables,
-- three in the auth password/mail tables. Hand-typing an inventory is how
-- the other seven would have been missed again.
--
-- Regenerate with:
--   SELECT conrelid::regclass, conname,
--          (SELECT string_agg(attname, ',' ORDER BY attnum)
--             FROM pg_attribute WHERE attrelid=conrelid AND attnum=ANY(conkey)),
--          confdeltype
--   FROM pg_constraint WHERE confrelid='users'::regclass;
--
-- `ON DELETE` is preserved exactly per constraint. RESTRICT on
-- `notes.primary_author_id` and `note_versions.created_by` is what stops
-- an author dangling off an append-only history; CASCADE on the
-- per-user rows (autocomplete, notifications, mail outbox) is what makes
-- deleting a principal clean up after itself. Both mean the same thing
-- after the swap, because the identity is the principal now.
--
-- NOT VALID + VALIDATE is the two-step: ADD ... NOT VALID takes a brief
-- lock and does not scan, and VALIDATE scans under a weaker lock that
-- does not block reads or writes. On a large `notes` table the one-step
-- form would hold an ACCESS EXCLUSIVE lock for the length of a full scan.
--
-- What this migration does NOT do: drop `users`, create the compat view,
-- or touch Keycloak. Those are gated on IDX-A4 (there is no native
-- password login yet), the A5 cut-over, and B1b's room checklist — see
-- docs/sprints/IDX-B2.md.

-- ── Guard ────────────────────────────────────────────────────────────
-- Refuse rather than create a dangling reference. Reached only if 0027
-- skipped a row for an email that already belonged to a native identity.
DO $$
DECLARE
    orphans int;
BEGIN
    SELECT count(*) INTO orphans
    FROM users u LEFT JOIN identities i ON i.id = u.sub
    WHERE i.id IS NULL;
    IF orphans > 0 THEN
        RAISE EXCEPTION
            'IDX-B2: % users row(s) have no identity. Re-run 0027 or resolve '
            'the email collision it reported before swapping foreign keys.',
            orphans;
    END IF;
END $$;


-- ── The swaps (13, generated) ────────────────────────────────────────

ALTER TABLE auth_mail_outbox DROP CONSTRAINT auth_mail_outbox_subject_sub_fkey;
ALTER TABLE auth_mail_outbox ADD CONSTRAINT auth_mail_outbox_subject_sub_fkey
    FOREIGN KEY (subject_sub) REFERENCES identities(id) ON DELETE CASCADE NOT VALID;
ALTER TABLE auth_mail_outbox VALIDATE CONSTRAINT auth_mail_outbox_subject_sub_fkey;

ALTER TABLE auth_password_events DROP CONSTRAINT auth_password_events_subject_sub_fkey;
ALTER TABLE auth_password_events ADD CONSTRAINT auth_password_events_subject_sub_fkey
    FOREIGN KEY (subject_sub) REFERENCES identities(id) ON DELETE CASCADE NOT VALID;
ALTER TABLE auth_password_events VALIDATE CONSTRAINT auth_password_events_subject_sub_fkey;

ALTER TABLE auth_password_reset_tokens DROP CONSTRAINT auth_password_reset_tokens_subject_sub_fkey;
ALTER TABLE auth_password_reset_tokens ADD CONSTRAINT auth_password_reset_tokens_subject_sub_fkey
    FOREIGN KEY (subject_sub) REFERENCES identities(id) ON DELETE CASCADE NOT VALID;
ALTER TABLE auth_password_reset_tokens VALIDATE CONSTRAINT auth_password_reset_tokens_subject_sub_fkey;

ALTER TABLE autocomplete_phrases DROP CONSTRAINT autocomplete_phrases_owner_user_id_fkey;
ALTER TABLE autocomplete_phrases ADD CONSTRAINT autocomplete_phrases_owner_user_id_fkey
    FOREIGN KEY (owner_user_id) REFERENCES identities(id) ON DELETE CASCADE NOT VALID;
ALTER TABLE autocomplete_phrases VALIDATE CONSTRAINT autocomplete_phrases_owner_user_id_fkey;

ALTER TABLE autocomplete_snippets DROP CONSTRAINT autocomplete_snippets_owner_user_id_fkey;
ALTER TABLE autocomplete_snippets ADD CONSTRAINT autocomplete_snippets_owner_user_id_fkey
    FOREIGN KEY (owner_user_id) REFERENCES identities(id) ON DELETE CASCADE NOT VALID;
ALTER TABLE autocomplete_snippets VALIDATE CONSTRAINT autocomplete_snippets_owner_user_id_fkey;

ALTER TABLE mfa_reminders DROP CONSTRAINT mfa_reminders_requested_by_fkey;
ALTER TABLE mfa_reminders ADD CONSTRAINT mfa_reminders_requested_by_fkey
    FOREIGN KEY (requested_by) REFERENCES identities(id) ON DELETE SET NULL NOT VALID;
ALTER TABLE mfa_reminders VALIDATE CONSTRAINT mfa_reminders_requested_by_fkey;

ALTER TABLE mfa_reminders DROP CONSTRAINT mfa_reminders_subject_sub_fkey;
ALTER TABLE mfa_reminders ADD CONSTRAINT mfa_reminders_subject_sub_fkey
    FOREIGN KEY (subject_sub) REFERENCES identities(id) ON DELETE CASCADE NOT VALID;
ALTER TABLE mfa_reminders VALIDATE CONSTRAINT mfa_reminders_subject_sub_fkey;

ALTER TABLE notes DROP CONSTRAINT notes_primary_author_id_fkey;
ALTER TABLE notes ADD CONSTRAINT notes_primary_author_id_fkey
    FOREIGN KEY (primary_author_id) REFERENCES identities(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE notes VALIDATE CONSTRAINT notes_primary_author_id_fkey;

ALTER TABLE note_versions DROP CONSTRAINT note_versions_created_by_fkey;
ALTER TABLE note_versions ADD CONSTRAINT note_versions_created_by_fkey
    FOREIGN KEY (created_by) REFERENCES identities(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE note_versions VALIDATE CONSTRAINT note_versions_created_by_fkey;

ALTER TABLE notification_digest_progress DROP CONSTRAINT notification_digest_progress_user_id_fkey;
ALTER TABLE notification_digest_progress ADD CONSTRAINT notification_digest_progress_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES identities(id) ON DELETE CASCADE NOT VALID;
ALTER TABLE notification_digest_progress VALIDATE CONSTRAINT notification_digest_progress_user_id_fkey;

ALTER TABLE notification_preferences DROP CONSTRAINT notification_preferences_user_id_fkey;
ALTER TABLE notification_preferences ADD CONSTRAINT notification_preferences_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES identities(id) ON DELETE CASCADE NOT VALID;
ALTER TABLE notification_preferences VALIDATE CONSTRAINT notification_preferences_user_id_fkey;

ALTER TABLE notifications DROP CONSTRAINT notifications_recipient_user_id_fkey;
ALTER TABLE notifications ADD CONSTRAINT notifications_recipient_user_id_fkey
    FOREIGN KEY (recipient_user_id) REFERENCES identities(id) ON DELETE CASCADE NOT VALID;
ALTER TABLE notifications VALIDATE CONSTRAINT notifications_recipient_user_id_fkey;

ALTER TABLE notification_user_settings DROP CONSTRAINT notification_user_settings_user_id_fkey;
ALTER TABLE notification_user_settings ADD CONSTRAINT notification_user_settings_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES identities(id) ON DELETE CASCADE NOT VALID;
ALTER TABLE notification_user_settings VALIDATE CONSTRAINT notification_user_settings_user_id_fkey;
