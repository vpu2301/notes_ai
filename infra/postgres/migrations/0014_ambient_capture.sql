-- 0014 — Ambient Capture v1: record WHICH surface produced a dictation
-- session's audio.
--
--   - `capture_source` distinguishes "a person dictated this in a
--     browser tab" from "a phone captured this" from "the room device
--     heard this" — reviewers and audit consumers need the provenance,
--     and the room-device runbook (docs/runbooks/ambient-device.md)
--     requires devices to declare themselves.
--   - `device_name` is an optional stable free-text label for the
--     capturing device/room (e.g. "Berlin 4F"). Allowed with any
--     source: a phone or browser profile may also carry a label.
--
-- Both arrive on the WS `start_session` message (dictation.v1 and .v2,
-- validated in dictation-service's protocol models) and describe the
-- ORIGINAL capture: a resume from a different surface never rewrites
-- them. Existing rows predate the feature and were all browser-borne
-- streams, so the DEFAULT backfills them truthfully.

ALTER TABLE dictation_sessions
    ADD COLUMN capture_source TEXT NOT NULL DEFAULT 'browser'
        CONSTRAINT dictation_sessions_capture_source_check
        CHECK (capture_source IN ('browser', 'mobile', 'room_device')),
    ADD COLUMN device_name TEXT
        CONSTRAINT dictation_sessions_device_name_len_check
        CHECK (device_name IS NULL OR char_length(device_name) BETWEEN 1 AND 128);
