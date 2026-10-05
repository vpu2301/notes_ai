-- 0067 — the admin "Meeting quality" dashboard (Grafana, read as funnel_reader).
--
-- After each real recording, an admin sees how the transcript and the note
-- went: duration, language, confidence, coverage, guards, speakers, spelling
-- unification, and the note's backend, model, prompt version, facts and lint
-- findings. Users never see it: it lives in Grafana (admin login, sign-up
-- off), not in the product.
--
-- * `transcription_jobs.quality` — a numbers-only summary the worker writes
--   on completion (asr_worker/quality.py): counts, shares, seconds, language
--   codes and enum reasons. Never a word, name or spelling.
-- * Column-level grants for funnel_reader, extending 0046/0060. Metadata only:
--     transcription_jobs   language, model, detected_language, queued_at,
--                          started_at, error_kind, quality,
--                          entity_unify_status, corrections_rev
--                          NOT error_detail, vocabulary_hint, speaker_names,
--                          speaker_name_candidates, previous_speaker_names
--     note_generations     job_id, step, windows_total/done/failed,
--                          prompt_version, backend, model_id, transcript_rev,
--                          error_kind
--                          NOT failed_ranges, snapshot_key, requested_by
--     transcript_corrections  id, tenant_id, job_id, source, status,
--                          confidence, created_at, updated_at
--                          NOT from_forms, to_text, occurrences, decided_by
-- transcript_corrections' restrictive tenant policy is TO app_role (0066), so
-- a permissive SELECT policy for funnel_reader is enough.

ALTER TABLE transcription_jobs ADD COLUMN quality JSONB
    CHECK (quality IS NULL OR jsonb_typeof(quality) = 'object');

GRANT SELECT (language, model, detected_language, queued_at, started_at, error_kind, quality,
              entity_unify_status, corrections_rev)
    ON transcription_jobs TO funnel_reader;
GRANT SELECT (job_id, step, windows_total, windows_done, windows_failed, prompt_version,
              backend, model_id, transcript_rev, error_kind)
    ON note_generations TO funnel_reader;
GRANT SELECT (id, tenant_id, job_id, source, status, confidence, created_at, updated_at)
    ON transcript_corrections TO funnel_reader;

CREATE POLICY funnel_reader_select ON transcript_corrections
    FOR SELECT TO funnel_reader USING (true);
