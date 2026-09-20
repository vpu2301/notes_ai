-- 0046 — Sprint 30: the weekly speaker-quality report reads as funnel_reader.
--
-- scripts/ops/speaker_quality.sql counts, across every tenant, how often
-- people correct the diarizer's speakers. It needs a handful of numbers and
-- labels from two tenant-scoped tables and nothing else, so the grant is
-- COLUMN-LEVEL on transcription_jobs:
--
--   granted   id, tenant_id, status, finished_at, result_first_read_at,
--             metadata (numbers + engine name: TranscriptionMetadata /
--             DiarizationStats — no text), diarization_rev,
--             diarization_runs, capture_context (source/client vocabulary)
--   NOT       speaker_names, speaker_name_candidates, previous_speaker_names
--             (who a speaker is, is CONTENT — ADR-0031), result/previous
--             storage URIs, error_detail, audio_id, requester_sub
--
-- transcription_speaker_edits holds labels (`SPEAKER_N`, CHECK-constrained),
-- segment indices, ints, timestamps and a bool — no names, no text. Its
-- one personal column, `actor_sub` (who made the edit), is not needed for
-- a count and is left out: the grant is column-level here too.
--
-- Both tables carry a RESTRICTIVE tenant policy that 0005/0043 created for
-- PUBLIC (every role). A permissive policy alone would therefore still
-- show funnel_reader zero rows. The restrictive policy is re-targeted TO
-- app_role — the only non-owner role holding any privilege on either table
-- (checked at 0046: app_role + the owner) — which is the shape `notes` has
-- had since 0009 and what 0040 relies on. A future role that is granted
-- these tables must be added to the restrictive policy's role list.

GRANT SELECT (id, tenant_id, status, finished_at, result_first_read_at, metadata,
              diarization_rev, diarization_runs, capture_context)
    ON transcription_jobs TO funnel_reader;
GRANT SELECT (id, tenant_id, job_id, result_rev, seq, kind, from_label, to_label,
              segment_indices, created_at, reverted_at, creates_label)
    ON transcription_speaker_edits TO funnel_reader;

ALTER POLICY transcription_jobs_tenant_restrictive ON transcription_jobs TO app_role;
ALTER POLICY transcription_speaker_edits_tenant_restrictive ON transcription_speaker_edits
    TO app_role;

CREATE POLICY funnel_reader_select ON transcription_jobs
    FOR SELECT TO funnel_reader USING (true);
CREATE POLICY funnel_reader_select ON transcription_speaker_edits
    FOR SELECT TO funnel_reader USING (true);
