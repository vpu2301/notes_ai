-- 0035 — Sprint 19: per-recipient share links (recipient viral loop).
--
-- 0016 gave a note ONE live "anyone with the link" token. A sender who
-- hands a client a link needs one *per recipient*: labelled, expiring
-- by default, revocable on its own, and attributable — "Tom opened it"
-- is the first signal the loop is measured on. So:
--
--   - `kind`            — `public` (0016 behaviour, still at most one live
--                         per note) or `recipient` (many per note).
--   - `label`           — the sender's own name for the recipient
--                         ("Tom @ Client"). Never shown on the page.
--   - `recipient_email` — optional; a label and, from Sprint 22, the
--                         delivery address. PII: revoking the link
--                         anonymises it (NULL), the label stays.
--   - `draft_acknowledged` — the sender ticked "I have reviewed this
--                         note" to share a non-finalized note; the page
--                         shows a DRAFT badge either way.
--   - `first_viewed_at` — the "reached the recipient" signal; set once.
--   - `cta_clicked_at`  — the "recipient clicked the product CTA"
--                         signal; set once.
--   - `ref_code`        — opaque, tenant-agnostic referral code carried
--                         into `/join?ref=` and auth-service `referrals`.
--                         Random, unrelated to any id: it must not let a
--                         reader guess a tenant or a note.
--
-- Existing rows are `public` (the default) and keep working unchanged.
-- `resolve_note_share_link` is untouched: the anonymous route reads the
-- link row itself on the tenant-scoped connection it opens afterwards.

CREATE TYPE share_link_kind AS ENUM ('public', 'recipient');

ALTER TABLE note_share_links
    ADD COLUMN kind               share_link_kind NOT NULL DEFAULT 'public',
    ADD COLUMN label              TEXT NOT NULL DEFAULT ''
                                  CHECK (char_length(label) <= 120),
    ADD COLUMN recipient_email    TEXT
                                  CHECK (recipient_email IS NULL
                                         OR char_length(recipient_email) <= 320),
    ADD COLUMN draft_acknowledged BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN first_viewed_at    TIMESTAMPTZ,
    ADD COLUMN cta_clicked_at     TIMESTAMPTZ,
    ADD COLUMN ref_code           TEXT UNIQUE
                                  CHECK (ref_code IS NULL OR char_length(ref_code) <= 32);

-- One live PUBLIC link per note stays; recipient links are many.
DROP INDEX note_share_links_live_idx;
CREATE UNIQUE INDEX note_share_links_live_public_idx
    ON note_share_links (note_id)
    WHERE revoked_at IS NULL AND kind = 'public';
CREATE INDEX note_share_links_note_live_idx
    ON note_share_links (note_id, created_at DESC)
    WHERE revoked_at IS NULL;
