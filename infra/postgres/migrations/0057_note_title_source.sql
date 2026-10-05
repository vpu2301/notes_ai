-- 0057 — Where a note's title came from.
--
-- A meeting note opens with a placeholder ("Meeting notes — 2026-09-22")
-- and the generation job gives it a real one once the transcript is in.
-- That rename must never land on a title a person chose, and "never"
-- has to survive a reload, a second device and a job that runs twice —
-- so the origin lives on the row, not in a client.
--
--   default — a placeholder the server made up; the job may replace it
--   ai      — the job already named it; it is not renamed again
--   user    — typed by a person (or taken from their calendar event)
--   NULL    — a note older than this column: never titled automatically
--
-- Every version append that changes the title without saying otherwise
-- flips it to `user` (`notes_repository.append_version`), so a rename
-- from any client is recorded by the same statement that stores it.
ALTER TABLE notes
    ADD COLUMN title_source text
        CHECK (title_source IN ('default', 'ai', 'user')),
    ADD COLUMN title_generated_at timestamptz;
