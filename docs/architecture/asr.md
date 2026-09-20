# ASR Architecture (Sprint 03)

This page is the durable mental model for the batch ASR path. Sprint 04
streaming reuses the engine + crypto + storage primitives; this doc is
its dependency.

## Service topology

```
        ┌──────────────┐    POST /asr/jobs    ┌───────────────┐
        │   browser /  │ ───────────────────▶ │  asr-service  │
        │  EHR client  │                       │ (CPU, multi)  │
        └──────────────┘                       └───────┬───────┘
                                                       │ 1. encrypt + put
                                                       ▼
                                               ┌───────────────┐
                                               │   Object store│
                                               │  mdx-audio    │
                                               └───────────────┘
                                                       │
                                                       │ 2. INSERT rows
                                                       ▼
                                               ┌───────────────┐
                                               │   Postgres    │
                                               │ audio_files / │
                                               │ transcription │
                                               │     _jobs     │
                                               └───────────────┘
                                                       │
                                                       │ 3. XADD asr:jobs
                                                       ▼
                                               ┌───────────────┐
                                               │     Redis     │
                                               │   Streams     │
                                               └───────┬───────┘
                                                       │
                                                       │ 4. XREADGROUP
                                                       ▼
                                               ┌───────────────┐
                                               │  asr-worker   │
                                               │  (GPU, N)     │
                                               └───────┬───────┘
                                                       │ 5. fetch audio
                                                       ▼  → ffmpeg → PCM
                                                       │  → VAD → Whisper
                                                       │
                                                       │ 6. encrypt + put
                                                       ▼
                                               ┌───────────────┐
                                               │   Object store│
                                               │ mdx-transcripts│
                                               └───────────────┘
```

## Envelope

```
┌─────────────────────────────────────────────────────────────────┐
│              KEK_master  (1 per environment)                     │
│              (file in dev, KMS in prod — ADR-0011)               │
│                          │                                       │
│                  wraps   ▼                                       │
│              KEK_tenant  (1 per tenant; tenant_keks)             │
│                          │                                       │
│                  wraps   ▼                                       │
│              DEK_object  (1 per audio file or transcript;        │
│                           ephemeral, never persisted plaintext)  │
│                          │                                       │
│                  encrypts ▼                                       │
│              ciphertext  (in the object store, header || ciphertext)        │
└─────────────────────────────────────────────────────────────────┘
```

AAD on every operation: `tenant_id.bytes || caller_aad`. The caller_aad
is the row id (e.g., audio_id, job_id) so the ciphertext is bound to
its logical home.

## Queue

Redis Streams. One stream `asr:jobs`. One consumer group
`asr-workers`. Workers are members of the group with distinct
`consumer` names (one per replica).

```
Producer (asr-service):
    XADD asr:jobs * value <json> key <job_id> h-tenant_id <…> h-job_id <…>

Consumer (asr-worker):
    XREADGROUP GROUP asr-workers <consumer-name> COUNT 1 BLOCK 5000 STREAMS asr:jobs >
    -- on success:
    XACK asr:jobs asr-workers <message_id>
    -- on stuck (no ack within 60s):
    XAUTOCLAIM asr:jobs asr-workers <consumer-name> 60000 0-0 COUNT 10
    -- on 3 retries:
    XADD asr:jobs:dlq * (move to DLQ)
    XACK asr:jobs asr-workers <message_id>
```

## Failure-mode table

| Where                  | What                          | Recovery                                |
| ---------------------- | ----------------------------- | --------------------------------------- |
| API: validator         | Reject upload                 | RFC 9457 problem detail; client retries |
| API: storage           | S3 put fails                  | 5xx; no row inserted; client retries    |
| API: DB                | INSERT fails after the S3 put | Orphan ciphertext → cleanup cron        |
| Queue: XADD            | Redis down                    | 5xx; orchestrator retries               |
| Worker: fetch          | Object missing                | Mark failed, `corrupt_audio`            |
| Worker: ffmpeg         | Decode fails                  | Mark failed, `corrupt_audio`            |
| Worker: Whisper        | OOM                           | Mark failed, `gpu_oom`; release cache   |
| Worker: Whisper        | Timeout                       | Mark failed, `timeout`                  |
| Worker: storage put    | S3 put of transcript fails    | Mark failed; XACK; alert                |
| Worker: ack            | Crashed before XACK           | XAUTOCLAIM reclaims → next consumer      |
| Worker: ack            | Reclaimed > 3 times           | Move to DLQ; ops investigates           |
| Worker: diarizer (in-process) | Engine cannot load     | Mark failed, `diarization_unavailable` (retryable) |
| Worker: diarizer (endpoint)   | Endpoint down / refuses | **Transcript completes without speakers**; `diarization_status='failed'`; the clients offer a re-run (ADR-0052) |

## Where diarization runs (ADR-0052)

The worker calls one `Diarizer` (`libs/diarization/protocol.py`); which
one is configuration, and the word-level attribution never knows:

```
asr-worker ── MDX_DIAR_ENGINE ──┬─ legacy    LegacyEcapaDiarizer  (in-process, CPU)
                                ├─ pyannote  PyannoteDiarizer     (in-process; needs a GPU to fit the budget)
                                └─ http      HttpDiarizer ──HTTP──▶ deploy/diar-server (GPU endpoint)
                                                                     └─ the same PyannoteDiarizer
```

`http` is what ships: community-1 costs 0.64–0.85 × audio on four CPU threads
against a 0.25 budget. Over that hop go the audio (lossless, in memory
only), the speaker-count hints and the roster policy; back come labelled
spans and counts. Never over it: tenant, job, user, filename, transcript
text — or a speaker embedding, which has no field in the payload.

Because the engine is now a remote dependency, its outage is handled
like one: the transcript completes, the row says the labelling failed,
and the user is offered a re-run. That asymmetry (loud in-process,
forgiving remote) is deliberate — see the failure table above.

## Speaker edits — fold order and index space (Sprint 28–30)

The stored transcript artifact is never rewritten. Speaker corrections are
rows in `transcription_speaker_edits`, folded onto the segments at every
read (`asr_service/domain/speaker_edits.py`):

- **Scope.** An edit belongs to one diarization revision (`result_rev` =
  `transcription_jobs.diarization_rev`). A re-run or an undo of a re-run
  bumps the revision and leaves older edits inert. `POST …/speakers/reassign`
  takes the client's `result_rev` and answers 409 `stale_result_rev` when
  it is not current — indices mean nothing across revisions.
- **Order.** Live edits apply in `seq` order only, so the fold is
  deterministic and independent of read time. A `merge` relabels every
  segment currently carrying `from_label` — including segments an earlier
  reassign moved there. A `reassign` relabels the segments it names to
  `to_label` (`NULL` = unattributed); a later merge of that label carries
  them along. The route resolves `to_label` through preceding merges, so a
  reassign always targets a surviving label; `"new"` allocates
  `SPEAKER_{max label ever seen + 1}` (`creates_label`), 8 live at most.
- **Index space.** `segment_indices` are indices into the STORED
  ARTIFACT's segments. The read path may fold a punctuation-only segment
  into its predecessor (NLP enrichment), so a served segment carries
  `artifact_indices` (all artifact segments it stands for) and a turn's
  `segment_indices` is the union of its segments' artifact indices. A
  reassign of a turn therefore moves exactly the artifact segments behind
  it, punctuation included. Clients treat the indices as opaque.
- **Roster.** Folded, then pruned: a label every segment was moved away
  from leaves the roster, names and stats; a created label joins them.
  A served segment is labelled by its HOST artifact segment
  (`artifact_index`); punctuation NLP folded into it follows the host. A
  segment moved to "Unknown" is `speaker_cleared` and never re-absorbed
  into a neighbouring turn. Undoing a move to a new speaker drops that
  label's name; allocation skips every label any edit ever used.
- **Known gap.** Edit responses (and the 8-speaker check) are built from
  the artifact without the NLP pass, so a label whose only remaining
  speech is a voice-command-only segment (NLP renders it empty) still
  counts there while the read view hides it. Rare; the next read is
  authoritative.
- **Uncertain turns.** `turn.uncertain` when a segment overlaps the
  engine's `overlap_ms` (persisted on the artifact since Sprint 30), when
  the worker smoothed a word's label, or when an unattributed segment was
  absorbed into the turn.
- **Anchors elsewhere** (note evidence, workflow-bridge): use
  `start_ms`/`end_ms` + artifact `segment_indices`, never a turn's
  position — reassigns reshape turns.

## Cross-references

- **ADR-0009** — inference engine choice.
- **ADR-0010** — queue choice.
- **ADR-0011** — envelope structure.
- **`docs/runbooks/asr-worker.md`** — operational playbook.
- **`docs/audit/event-kinds.md`** — `asr.*` kinds emitted along the path.
