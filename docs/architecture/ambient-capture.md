# Ambient Capture (meeting scribe)

Ambient capture turns a conversation happening in a room into a
speaker-attributed, structured note — without anyone typing. It is the
business equivalent of an "ambient scribe": the microphone listens, the
platform transcribes, separates speakers, and drafts the note.

## The three capture paths

```
1. LIVE, browser/mobile          2. LIVE, room device            3. UPLOAD, any recording
   (a laptop/phone in the           (dedicated hardware in           (phone memo, handheld
   meeting, SPA open)               the meeting room)                recorder, call export)
        │                                │                                │
        │ WS dictation.v2                │ WS dictation.v2                │ POST /asr/jobs
        │ mode=conversation              │ mode=conversation              │ diarize=true
        │ capture_source=browser        │ capture_source=room_device     │
        ▼                                ▼                                ▼
   dictation-service ◄──────────────────┘                           asr-service
        │  VAD → windowed Whisper → diarization (ECAPA)                  │ enqueue (Redis Streams)
        │  partials/finals + SPEAKER_N attribution                       ▼
        │  client may name speakers (SetSpeakerMapping)             asr-worker
        │                                                                │ Whisper transcript
        │ finalize                                                       │ + offline diarization
        ▼                                                                ▼
   speaker-turn transcript                                    speaker-attributed result
        │ draft push                                                     │
        ▼                                                                ▼
   note-service  ◄────────────────────────────────  POST /v1/notes/from-transcript
        │
        ▼
   structured note (meeting_notes template): dialogue + sections,
   versioned, searchable, exportable to PDF
```

All three paths end in the same place: a note whose body carries the
conversation as speaker-turn dialogue lines, ready for editing,
finalization, and search.

## Speaker handling

- Diarization (silero VAD + ECAPA embeddings + clustering, ADR-0034)
  produces neutral labels `SPEAKER_1..N`. The platform never guesses who
  a speaker *is*.
- Live sessions: the online clusterer separates two speakers; the client
  can assign display names during or after the meeting
  (`SetSpeakerMapping`); the finalized transcript and the draft note use
  those names.
- Batch jobs (ADR-0045): the whole recording is clustered at once
  (average-linkage agglomerative, up to 8 speakers), and speakers are
  attributed per *word*, so a Whisper segment that spans two people is
  split at the change. `GET /asr/jobs/{id}/result` returns the
  transcript pre-structured as `turns` (one per speaker change, long
  turns broken into paragraphs at pauses and sentence ends) plus a
  `speaker_names` map; the web and macOS transcript tabs render those
  turns, and `POST /v1/notes/from-transcript` writes them as
  `Name: paragraph` blocks.
- Naming: a person renames `Speaker 2` → `Olena` in either app;
  `PUT /asr/jobs/{id}/speakers` stores the label → name map on the job,
  so both apps and every later read agree. While the note is a draft the
  app also rewrites the turn prefixes in the note body; a finalized note
  keeps its text.

## Room devices

A meeting-room device is a first-class, least-privilege identity:

- Keycloak confidential client with a service account holding the
  **`device`** role: it can start/read/finalize dictation sessions,
  submit and read batch transcription jobs, and read templates —
  and nothing else. A compromised device cannot read any note, search
  anything, or see the tenant roster.
- Sessions it opens carry `capture_source=room_device` and a
  `device_name` (e.g. `hq-4f-boardroom`), so every capture is
  attributable in the session list and audit trail.
- Provisioning/rotation: `docs/runbooks/ambient-device.md`.

## Privacy & recording posture

- Audio and transcripts are envelope-encrypted per tenant at rest
  (ADR-0011); decrypted PCM lives only in RAM-backed tmpfs during
  processing.
- Recording a conversation is subject to local law and company policy
  (many jurisdictions require participant consent). The platform gives
  deployers the hooks — visible device naming, audit events for every
  session, per-tenant data isolation — but announcing/consent workflow
  is a product/deployment concern, deliberately not enforced in the
  backend.

## Performance posture

Same as streaming dictation: on CPU dev hardware the pipeline favors
transcript completeness over latency (30 s windows, ~1.1× realtime,
words can take up to the hop to appear). Ambient capture tolerates this
well — the note is written after the meeting. GPU deployments restore
low-latency partials (see `infra/compose/gpu.yml` and the tuning notes
in `docker-compose.override.yml`).

## Configuration

| Env | Service | Purpose |
|---|---|---|
| `MDX_DIAR_MODEL_DIR` | dictation-service, asr-worker | baked ECAPA model dir |
| `MDX_CONVERSATION_SESSION_WEIGHT` | dictation-service | capacity booking for meeting sessions |
| `MDX_WINDOW_SECONDS` / `MDX_WINDOW_MIN_FOR_PARTIAL_SECONDS` | dictation-service | latency/throughput trade |

## Where this is useful

See `docs/product/ambient-use-cases.md` for the business scenarios this
feature is built for.
