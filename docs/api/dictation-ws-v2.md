# `dictation.v2` — conversation (meeting) mode & speaker diarization

Sprint 14. Companion to `dictation-ws-v1.md`, which stays the canonical
reference for everything v2 does not change. **v1 is byte-stable**: no
v1 model gained a field, and a v1 client that receives a v2 frame
rejects it cleanly via `extra="forbid"` (the sprint-04 promise, proven
in `tests/unit/test_protocol_v2.py`).

Read this together with **ADR-0034** (why the diarization backend is
Silero VAD + ECAPA + online clustering, with measured DER) and the
**ADR-0013 amendment** (the commit-policy fixes that made real
transcripts possible at all).

## The honesty principle

**Diarization is probabilistic. Every speaker label on this wire is a
PROPOSAL, never a fact.**

- Labels are anonymous (`S1`/`S2`) — the display name a label carries
  is a *separate*, client-controlled mapping with neutral
  `SPEAKER_1..N` defaults. The server never guesses who a speaker is.
- `UNKNOWN` is a first-class answer. Overlapping speech, a
  turn-straddling segment, or a third voice yields `UNKNOWN` rather
  than a guess.
- `null` is also legal: labels may trail the text by up to one window.
  **Render text immediately; colour it when the label lands.**
- Nothing downstream (note synthesis, the record) may treat a label as
  ground truth until the user finalizes. A mislabeled turn must be one
  tap to rename (`set_speaker_mapping`).

## Negotiation

The client offers subprotocols in `Sec-WebSocket-Protocol`; the server
picks by preference, **v2 over v1**:

```
Sec-WebSocket-Protocol: dictation.v2, dictation.v1
→ server accepts with: dictation.v2
```

A v1-only client is unaffected. Offering neither is
`400 unsupported_protocol` (unchanged).

A session is **exactly one version for its whole lifetime**:

- `protocol_version` on a client frame must equal the negotiated
  version, else `error{code: unsupported_protocol}`.
- A reconnect (`resume_session_id`) that negotiates a *different*
  subprotocol than the original session gets the uniform
  `session_not_found` — a v1 tab must never receive v2 frames.

`PROTOCOL_VERSION_V2 = 2`.

## Client → server

### `start_session` (v2: gains `mode`)

```jsonc
{
  "type": "start_session",
  "protocol_version": 2,
  "language": "uk",              // "uk" | "en" | "de"
  "mode": "conversation",        // NEW: "dictation" (default) | "conversation"
  "vocabulary_hint": "Klarnote OKR roadmap",  // optional free text → Whisper initial_prompt
  "capture_source": "room_device", // "browser" (default) | "mobile" | "room_device"
  "device_name": "Berlin 4F",      // optional 1–128 char device/room label
  "template_id": "…",            // needed for a draft at finalize
  "target_kind": "generic",
  "resume_session_id": null
}
```

`capture_source` and `device_name` are the **Ambient Capture v1**
provenance fields, present on *both* v1 and v2 `start_session`
(additive, like `vocabulary_hint`). `capture_source` says which surface
produced the audio; `device_name` is a stable free-text label for the
capturing device/room and is allowed with **any** source. Both are
validated (unknown source or an out-of-bounds name is `bad_message`),
persisted on `dictation_sessions` (migration `0014_ambient_capture`),
carried in the `dictation.session.started` audit payload
(`device_name` only when set), and echoed on `GET /dictate/sessions`
list and detail rows. A room device MUST send
`capture_source: "room_device"` — see
`docs/runbooks/ambient-device.md`.

`mode: "conversation"` points the microphone at a meeting: the audio is
diarized and every committed segment carries a speaker proposal. There
is **no precondition beyond auth** — no linkage to any other record.

If the diarizer cannot load, conversation start fails **loudly** with
`error{code: "worker_failed", recoverable: true}` (close 1013) rather
than silently producing an unlabeled transcript.

### `set_speaker_mapping` (v2, new)

The user's naming of the diarized speakers. **Authoritative from the
moment received** — the mapping replaces the neutral defaults for the
rest of the session.

```jsonc
{ "type": "set_speaker_mapping", "mapping": { "S1": "Alice", "S2": "Bob" } }
```

Values are free-text display names (1–128 chars). Labels not named
keep their `SPEAKER_N` default. Sent on a dictation-mode session it is
`error{code: bad_message, recoverable: true}`.

The server acknowledges with a `speaker_mapping_updated{manual: true,
confidence: 1.0}` carrying the full current mapping.

## Server → client

### `partial` / `final` (v2: gain speaker fields)

```jsonc
{
  "type": "final",
  "session_id": "…", "seq": 12,
  "text": "почнімо з підсумків спринту",
  "start_ms": 7120, "end_ms": 8740,
  "words": [ /* unchanged TokenTiming */ ],
  "avg_confidence": 0.91,
  "is_provisional": false,
  "voice_command": null,

  // v2 additions:
  "speaker": "S2",                 // "S1" | "S2" | "UNKNOWN" | null
  "speaker_confidence": 0.84,      // 0..1, null when speaker is null
  "speaker_mapping_hint": { "S1": "SPEAKER_1", "S2": "SPEAKER_2" }  // or client names
}
```

| `speaker` | meaning | FE |
|---|---|---|
| `"S1"` / `"S2"` | proposal with `speaker_confidence` | colour the turn; allow one-tap rename |
| `"UNKNOWN"` | diarized, but genuinely ambiguous | render text plainly; invite assignment |
| `null` | not diarized *yet* (labels trail by ≤1 window) | render text now, colour when a later frame resolves it |

`speaker_mapping_hint` is the current label → display-name mapping
attached for convenience; `speaker_mapping_updated` is the
authoritative change notification.

### `speaker_mapping_updated` (v2)

```jsonc
{
  "type": "speaker_mapping_updated",
  "session_id": "…",
  "mapping": { "S1": "Alice", "S2": "Bob" },
  "confidence": 1.0,
  "rationale": "manual override",
  "manual": true
}
```

Emitted as the acknowledgement of a `set_speaker_mapping`. The FE
relabels already-rendered turns. It carries no `seq` and does not
advance the partial/final sequence. There is no server-side identity
inference: until the client names speakers, labels render under the
neutral `SPEAKER_1..N` defaults.

## Limits (pilot, documented — not bugs)

- **Two speakers.** A distinct third voice is reported `UNKNOWN`, never
  crammed into `S1`/`S2` (verified: 0 mislabeled third-voice words).
  A bystander whose voice is very close to a participant's cannot be
  separated by this backend at all (ADR-0034 §limitations).
- **Rapid sub-second turns** raise the `UNKNOWN` rate sharply
  (measured 38% on the stress fixture) — embeddings are unreliable
  below ~0.6 s of speech. The system abstains; it does not guess.
- Labels can trail text by one window; they never *retro-lie* (a
  committed label is not silently changed, though the display-name
  *mapping* over labels can change, which is what
  `speaker_mapping_updated` is for).

## Voice commands are OFF in conversation mode

A meeting participant saying «новий абзац» mid-sentence must not edit
the record. The finalize-time NLP pipeline runs with
`stages_disabled=["voice_commands"]` for conversation sessions: those
words stay **verbatim text** and no operation is produced. Dictation
mode is unchanged. Enforced server-side (nlp-service skips the stage)
with a defence-in-depth drop in dictation-service if any operation
arrives anyway.

## Finalize, persistence, drafts

Unchanged flow (`end_session` → `session_terminated`), plus:

- The persisted transcript (`dictation_sessions.transcript_jsonb`)
  gains, **for conversation sessions only**, per segment: `id` (UUID),
  `speaker`, `speaker_confidence`, `speaker_name`; and per word:
  `speaker`, `speaker_confidence`. A **dictation-mode transcript is
  byte-identical to the pre-sprint-14 shape** — existing consumers are
  untouched.
- `dictation_sessions.mode` records `'dictation' | 'conversation'`.
- On finalize a **note draft** is created through the existing
  `POST /v1/notes` (sprint-08 hand-off — no parallel write path),
  authored with the caller's own bearer, carrying
  `source_session_id` and the segment UUIDs in
  `transcript_segment_ids`. The dialogue is rendered as speaker-turn
  lines using the display names (`Alice:` / `SPEAKER_2:` /
  `UNKNOWN:`).
  Draft creation never fails a finalize: the transcript is already
  persisted, and a skip is a `conversation.draft.create_failed` audit
  row (common reason: the session had no `template_id`).

## Capacity

A conversation session holds two models resident, so it costs
`MDX_CONVERSATION_SESSION_WEIGHT` (default **2**) capacity slots
against `MDX_PER_WORKER_MAX_SESSIONS` (default 4): **4 dictation OR
2 conversation OR a weighted mix**. Over capacity →
`error{code: gpu_full, recoverable: true}`, close 1013, as today.

> The weight is currently a configured estimate, not a GPU
> measurement — the A10G rig re-measures it before staging
> (todo.md §S14).

## Resume

Resume semantics are unchanged from v1 (§"Reconnection sequence"). The
speaker timeline lives on the session context beside the committed
transcript, so an in-process resume preserves speakers up to the
committed high-water mark; the version-pinning rule above applies.

`capture_source`/`device_name` describe the **original** capture: a
resume keeps the session's stored values, and whatever the resume
`start_session` frame carries (a phone picking up a room-device
session, say) never overwrites them.

## Audit kinds

`dictation.session.started` gains `mode` + `protocol_version` in its
payload, plus `capture_source` (and `device_name` when set — Ambient
Capture v1). New: `conversation.speaker_mapping.manual_set`,
`conversation.draft.created`, `conversation.draft.create_failed`
(warn). See `docs/audit/event-kinds.md`.

## Hand-off to note synthesis

The synthesis contract is fixed here, additively:

- `SynthesisInput.transcript` entries gain optional `speaker` and
  `speaker_name`, fed directly by the persisted conversation
  transcript above (already carries both, per segment and per word).
- The grounding check must add **speaker attribution** to its entity
  sweep: a drafted *"Alice reported X"* where X was **Bob's**
  utterance is a grounding violation and must be flagged —
  misattributing a statement inverts its meaning.
- Segments whose `speaker` is `UNKNOWN`/`null`, or whose
  `speaker_name` is unset, must **not** be attributed to a named
  participant in generated prose.
