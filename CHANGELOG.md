# Changelog

## Unreleased — A live meeting note writes itself too

### Added
- **Summary Engine v2 — Q1, measure first** (`note-service`, `scripts/eval`): the notes eval
  finally measures the engine. Until now the harness sent `turns[].text` and the engine reads
  `turns[].paragraphs`, so the pipeline arm only ever scored an empty transcript; it now sends the
  result view the worker snapshots (names, recording date, name candidates, the template's
  sections) and exits 2 when a non-empty transcript yields no windows. New: every metric of the
  2026-09-22 audit (`scripts/eval/notes_scoring.py` — unsupported lines, invented claims,
  prompt-example echo, coverage by third, excluded speech, recording type, redundancy, entities,
  hedges, attribution), gold format v2 with a validator (`make eval-notes-validate`), three
  synthetic fixtures (a German news podcast shaped like the audited episode, a Ukrainian lecture,
  an English one-on-one), regression checklists (`make eval-notes-assert`; r01 = the audit), an
  eval-only model-judge column (`--judge`), `compare_notes.py` and a nightly workflow. Every
  written line now carries its kind and the fact ids it rests on (`RenderedSection.lines`; text
  unchanged, byte for byte). Every prompt example is now about an invented board-game company,
  and a line or fact that copies one is dropped: the "Der Start im November bleibt das Ziel"
  sentence was the German summary prompt's own example, not another workspace's recording
  (`docs/security/2026-09-22-november-sentence.md`). `PROMPT_VERSION` is `2026-10-6`.
- **Summary Engine v2 — Q2, nothing real dropped, nothing unsupported written** (`note-service`):
  a monologue's pieces get their own line numbers, so one "noise" flag no longer silences a whole
  story; the model's noise flags are confirmed by code (short and empty, provably another
  language, or a duplicate) and capped at 2 % of the speech; a window's fact budget follows its
  density (8–24); a fact whose text does not mean what its quote says is dropped (actions,
  decisions, numbers) or flagged; every summary sentence, topic bullet and framing sentence must
  be supported by the facts it cites (`meeting_doc/support.py`, shared with the eval), with one
  strict retry and a code-only key-fact overview when the model will not stay on its facts.
  `GET /v1/notes/{id}/generation` gains `excluded_ranges` and `coverage` (older generations: `[]`
  / `null`). New metrics and two alerts (`NoteGenerationNoiseOverridden`,
  `NoteGenerationUnsupportedLines`); `mdx_note_generations_total` is now actually recorded, so
  `NoteGenerationFailureRate` can fire. `PROMPT_VERSION` is `2026-10-7`.
- **Summary Engine v2 — Q3, the document fits the recording** (`asr-service`, `note-service`, web;
  migration 0058): a conversation's transcript is served verbatim — diarized results skip
  nlp-service's rewriting stages and relative words resolve against the recording day (Sprint G0),
  so "heute" stays "heute". Before extraction, a recording on the generic template is classified
  (one small call plus code rules; the author's meeting type or a specific template always wins)
  into meeting, client/sales call, interview, one-on-one, podcast/broadcast, lecture/webinar or
  voice memo, and a broadcast or memo is extracted without decisions or tasks
  (`Family.excluded_kinds`). The render writes each fact once: no key-fact block above topics, no
  bullet that repeats a summary sentence or another topic, no single-bullet topic, topics in the
  recording's order. The "Hinweis zum Transkript" paragraph (drawn on the web as a speaker called
  "HT") is gone: the web shows "Not included: 00:45–00:52 (background speech)" under the status,
  each range opening the transcript there, and the note's type pill says "Podcast / broadcast"
  instead of "Meeting notes" when that is what it was. Spoken dates are resolved in the tense they
  were said in ("am Montag … gewesen" → the Monday before) as an annotation on each fact; the
  words are never rewritten. `GET …/generation` gains `recording_type`, `recording_type_source`
  and `language`. `PROMPT_VERSION` is `2026-10-9`.
- **Summary Engine v2 — Q4, names, attribution, coverage** (`note-service`): names the workspace
  knows come out right in the note — the calendar's attendees, the roster, the ASR's name
  candidates and the workspace glossary (`heard_as`) now reach the engine, and a misheard name is
  respelled in the line (never in the quote; the fact records the correction). Names nobody knows
  go to the model once per generation, names and subject only, accepted only close to what was
  heard and never onto another participant; a far proposal leaves the spelling with "(?)"
  (`MDX_NOTE_ENTITY_MODEL_TIER`, **off by default**: 0/8 precision on the stack model, gate 0.9). Every opinion, forecast, estimate, proposal or
  allegation carries who holds it (`attributed_to`, verified like an owner; a speaker's own view is
  theirs; a quoted clip gets none): records end "— laut Reinbold" / "(Vorschlag: Söder)" and get
  "Voraussichtlich:" / "Schätzung:" when they carried no hedge, all in code; a summary sentence
  that drops the holder or the hedge is not written. Facts with a number, a date or a person are
  kept in their nearest topic whatever the model wrote about; two topics over the same stretch of
  the recording are merged. Blind pairwise rating tooling (`scripts/eval/notes_pairs.py`).
  The never-called `glossary.canonical_owner` is removed. A window whose facts carry line numbers instead of quotes is asked once more. `PROMPT_VERSION` is `2026-10-11`.
- **Summary Engine v2 — Q5, every line traceable** (`note-service`, web; migration 0059): every
  written line of a generated note — summary sentences, the framing, topic bullets, key dates,
  items — is a row with the evidence of what it cites, keyed the way the corrections routes key a
  line. On the web, each such line opens its words, when and by whom they were said, and plays the
  recording around them; a forecast, estimate, opinion, proposal or allegation carries a chip with
  whose it is; a respelled name shows what was heard. A "Termine & Fristen" / "Key dates" block
  lists what the recording scheduled or set a deadline for, each with a calendar file
  (`GET /v1/notes/{id}/dates/{key}.ics`). Short / Standard / Detailed is a view over the same rows,
  never a new version. A "Names in this note" panel lets the author accept a respelled name (it
  becomes a glossary term, so the next generation spells it that way) or reject it (the line goes
  back to what was heard). `GET …/generated-items?generation=current` and the new row fields are
  additive. Nothing of this reaches the shared page, the client version or the PDF.
- **Summary Engine v2 — Q6, reconciled with note titles** (`note-service`): one title mechanism
  (ADR-0059's `title_source`; the engine never writes a title) with the engine's two guards — a
  suggested title that copies a prompt example or names something the transcript never says is
  not written (`note_title.skipped`, reason `example` / `unsupported`); one noise policy
  (ADR-0059's "never most of the window" is now a `confirm_noise` rule, counted as advisory);
  the job classifies, then names, then extracts; the title prompt joins the pinned prompt
  fingerprint. `PROMPT_VERSION` is `2026-10-12`. Migrations stay 0057 (title source), 0058
  (recording types), 0059 (generated lines); the next free number is 0060.
- **A meeting note names itself** (`note-service`, Mac, iPhone; ADR-0059, migration 0057): a
  recording's placeholder title ("Meeting notes — 2026-09-22") is replaced, once, with a 3–8 word
  title in the spoken language, taken from across the whole transcript by the `note.generate` job
  before it writes the document. `notes.title_source` (`default` / `ai` / `user`) records where a
  title came from; any rename from any client sets `user`, and only `default` is ever replaced,
  checked again under the row lock at write time. Too little speech keeps the placeholder; a
  failed call changes nothing. Older notes are left alone. The Mac and iPhone no longer send their
  own "Meeting <date>" as a title, and pick up the server's title in their recents.
- **Generate Summary** (Mac, iPhone, web; `note-service`, ADR-0058 §5): the Notes tab of a draft
  made from a recording that was never written up — older than the engine, or the run never
  started — now shows one sentence and a *Generate Summary* button instead of nothing. It calls
  `POST /v1/notes/{id}/generation` as it already existed, the tab follows the run ("Writing this
  note — 3 of 8 minutes read") and shows the sections when it lands; a failed run says why and
  offers *Try again* in the same place. The button appears nowhere else. The meeting templates
  gain an *Overview* section (`summary` role) under *My notes*, because the engine's summary had
  no section to land in; the writer now fills a section the template has but an older note's
  content lacks (every client already draws it, empty), and the summary prompt asks for the third
  person — never *we*, *I* or *our* — with no filler. `PROMPT_VERSION` is `2026-10-2`.

### Changed
- **Structure follows content** (`note-service`, `note_models`, Mac, iPhone, web; ADR-0058 §6): the
  note view no longer draws the template. Every client renders the sections the content HAS, in
  its order, headed only when a section has a name — the template's for a template section, its
  own `title` (new, optional, on `NoteSection`) for one the engine made — and nothing for the
  author's pad or the engine's opening block. Empty sections are not drawn; while a note is
  editable the pad, typed fields and (on form-shaped templates without a pad) the template's own
  fields stay reachable. No "required" tags. The engine writes an unheaded opening block
  (`gen:overview`: framing, summary, key points, transcript note) and one `gen:<slug>` section
  per topic the conversation actually had — none for a single-subject or short conversation (a
  topic needs five facts and a real change of subject) — instead of a `### `-headed *Discussion*;
  nobody is listed as an attendee automatically; decisions, actions, open questions, risks and
  the next meeting go to the template's section when it has one, else to a headed section of
  their own, and only when there is content. On a re-run, what the engine wrote last time and
  does not write again is removed (generated) or emptied (template), unless a person edited it.
  Section labels, the PDF, the shared page, the client version and Markdown exports follow the
  same rule: no name, no heading. A section without a title has the canonical bytes it always
  had, so no version hash changes. The meeting templates' *Overview* section from earlier in the
  day is gone again; the block is the engine's.
- **Context-aware notes** (`note-service` engine, prompt `2026-10-4`): the engine now reads the
  verified facts once as a whole before writing — a context pass returns the conversation type,
  subject, 3–7 themes, one framing sentence and the 3–6 facts a reader must know first — and the
  topic and summary steps are written against that brief, in parallel. The Overview opens with
  the framing sentence ("Interview with a defence expert on the war in Ukraine…"), the Discussion
  opens with a *Key points* block above the topic headings, and topics are ordered by weight,
  not transcript order. Every fact carries a `certainty` (fact, estimate, prediction, opinion,
  proposal, allegation) the prompts must keep in the text — an estimate stays "was estimated at";
  flat openers ("It was noted that", "Es wurde festgestellt, dass", "Було зазначено, що") are
  stripped in the renderer while hedges that carry certainty are kept. The extractor flags turns
  that are not the conversation — background speech, another language, an artifact, a duplicate,
  an unrelated fragment — from a closed vocabulary; facts quoted from them are dropped, and the
  Overview ends with a one-line *Transcript note* rendered in code, never from model prose. The
  framing sentence is number-checked against the facts like a summary sentence, and every id the
  context pass names must be one it was given.

### Fixed
- **A recording no longer yields an empty note in silence** (`note-service` engine, all clients):
  NOTE-2026-00040 ran the engine automatically, extracted ten facts and wrote nothing, and the
  Notes tab showed neither a word nor a button. Three causes. The small model copies the turn
  header ("[0] Speaker 1 (00:00): ") into every quote, and the verbatim check failed on all of
  them — the header is now stripped from the quote before it is located, as it already was from
  the text. The model also flagged the recording's only substantive turn as "background"; a turn
  that is more than half the window's words is now never noise, because it is the recording. And
  a finished run that wrote nothing looked, to the clients, like a run that had nothing to say:
  `GET /v1/notes/{id}/generation` now carries `sections_written`, and web, Mac and iPhone show
  "Nothing could be written from this recording" with *Try again* when it is zero.
- **Meeting notes read as a business record, not a retelling** (`note-service` engine, prompt
  `2026-10-3`): a generated note showed raw fact ids in the Discussion bullets
  ("…(d96df9628cf97a1b)"), a Decisions section full of verbatim asides ("Man war sehr
  zögerlich…"), and narration ("man glaubte, dass…"). Three causes, three fixes. The reduce
  prompts asked for ids "in every bullet" and a small model wrote them into the prose: they
  now go in `fact_ids` only, and the renderer strips any id it still finds and keeps it as a
  citation. The agreement test counted "ja", "okay", "passt" and "добре" as consent, so in an
  interview every proposal near one became a decision: those words are gone from the pattern,
  and a decision whose text is the quote copied is filed as a key point. The extraction and
  reduce prompts (en/de/uk) now ask for one neutral third-person or impersonal business
  statement per fact — never "X said/thinks", never "we", no greetings, filler or repeats, a
  proposal stays a proposal — with a third worked example showing the rewrite. Clients treat a
  `superseded` latest run like none, so *Generate Summary* is offered again after an
  operator reset.
- **A recording survives its live note being binned** (`note-service`, migration 0056, Mac,
  iPhone, web): since Sprint 34 the note exists from the first second of a meeting, so an author
  who opened that still-empty note mid-recording and chose *Move to Trash* left the transcription
  with nowhere to land — `POST /v1/notes/{id}/transcript` was a 404 (`note not found` on the
  home page), and `from-transcript` a 409 `already_assigned`, because the unique index on
  `source_asr_job_id` still counted the trashed row. The index now guards live notes only, the
  three "who owns this job" lookups skip the bin, and every capture client drafts a fresh note
  from the transcript when the live one is gone at Stop (a bin on any device also unbinds the
  running capture, so autosave stops writing into a 404). The trashed row keeps its versions.
- **No automatic notes on a note opened at Record** (`note-service`): `POST /v1/notes/{id}/transcript`
  — the route the Mac, iPhone and web capture call when the recording finishes on a note that
  already existed — still carried Sprint 34's "no generation engine yet" placeholder. It put the
  transcript in a section and marked the capture `ready`, and no `note.generate` job was ever
  queued, so the Transcript tab was full while the Notes tab stayed empty. Only `from-transcript`
  (upload, older clients) started the engine. The route now starts it in the same transaction
  as the transcript version, with the same rules: off for the workspace or over budget is not
  an error, a missing object store or model never costs the capture, and silence starts no run.
  Progress is on `GET /v1/notes/{id}/generation`; the meeting state stays `ready`, since nothing
  moves a capture out of `generating` and a stalled run must not look like a stuck recording.
- Regression tests: `services/note-service/tests/unit/test_notes_meeting.py` (engine started,
  engine failure harmless, silence starts nothing).

## Unreleased — A silent recording is `no_speech`, not a transcript

### Fixed
- **Silence no longer reaches the decoder** (`asr-worker`): when Silero heard no speech the VAD
  handed Whisper the whole file as one run, and Whisper given silence plus the workspace
  glossary as `initial_prompt` wrote the prompt back — NOTE-2026-00033 was 28 minutes of
  "Gysi, Moderator." from a microphone that delivered zeros. `detect_speech` now returns an
  empty list, the engine returns no segments without calling the language detector or the
  decoder, and the processor files the job as `no_speech` (the gate that already existed).
- **Prompt echoes over non-speech are dropped**: a segment made only of the prompt's words
  that the decoder itself rates `no_speech_prob ≥ 0.5` is logged (`whisper.prompt_echo_dropped`)
  and skipped; the same words at a low probability are speech and stay.
- Regression tests: `services/asr-worker/tests/unit/test_silence_guard.py`.

## Unreleased — Diarizer v2 decided and hosted (ADR-0052, Sprint 29 B-9)

### Added
- **Speaker diarization on a GPU endpoint** (`deploy/diar-server`): our own image running the
  same pyannote community-1 pipeline the worker can run in-process, so labels do not depend on
  where the model ran. `MDX_DIAR_ENGINE=http` + `MDX_DIAR_HTTP_BACKEND`; backends `hf_eu_diar`
  (staging/prod) and `dev_mac_diar` (the Mac) in `config/models.yaml`; endpoint spec
  `deploy/hf/endpoints/diar.yaml`. The endpoint receives audio, hints and the roster policy —
  no tenant, job, user, filename or text — stores nothing, and returns labels, never embeddings.
- `diarization.HttpDiarizer` + `diarization.wire` (one payload definition, imported by both
  sides), `diar_http` as a backend kind in `libs/models`.
- **A diarizer outage no longer costs a transcript**: with a remote engine the job completes
  without speakers and records `diarization_status='failed'`, which the clients already turn
  into a re-run offer. In-process engines still fail the job (a broken deployment should be loud).

### Changed
- **ADR-0052 is Accepted**: v2 measured on the gold set — DER 0.182 vs 0.378 on test (−52 %),
  unattributed speech 21 % → 9.5 %, two-speaker count 4/4, 1–4 speakers 87 %. It meets the
  pre-registered rule. Hosting is shape B because community-1 needs **0.64–0.85 × audio on four
  CPU threads** against a 0.25 budget (0.13–0.15 × on a GPU).
- pyannote community-1 weight digests resolved and pinned (`scripts/models/prepare_pyannote.py`,
  worker Dockerfile, `docs/models/PINS.md`); the gated fetch is a BuildKit secret as before.
- Eval commands pin `pyannote.metrics>=4` — pyannote.audio 4 requires it (the documented
  `<4` combination cannot resolve). Scores are unchanged (checked on one file, both versions).
- Egress allowlist gains the diarization endpoint; `huggingface.co` and `otel.pyannote.ai`
  stay blocked and the egress test covers shape B.

### Fixed (from review, before anything shipped)
- The server buffered uploads to a **temp file** (Starlette spools multipart above 1 MiB) and did
  it **before** the token was checked — audio on disk, reachable unauthenticated. Auth and the
  size cap now run in middleware, before the body is read, and nothing spools.
- The remote path turned unattributed speech into a speaker called `UNKNOWN`, with its own turn
  and roster entry — it would have skewed the dual-channel count hint and the shadow metric.
- The worker's token and the server's token were different secrets, so every request would have
  been a 401 that no one saw: the job simply completed without speakers. The token now travels in
  its own header and `/health` reports whether it would be accepted, so a mismatch fails at startup.
- Retries gave up after ~6 s against a declared 240 s cold start (the first job after every idle
  spell lost its speakers); they now cover the backend's cold start.
- A dual-channel capture fell back to the mono path when the ENDPOINT was down, re-uploading the
  whole recording — up to nine uploads per job. The fallback is for channel bugs only now.
- Added: one pass at a time on the server, a bound on DECODED audio length (a near-silent FLAC
  expands enormously), CPU hosting refused, tracing headers stripped (they identify the worker
  trace, whose spans carry job and tenant ids), a configurable timeout slope, and the connection
  pool closed at shutdown. Diarization wall time no longer includes word attribution.

### Known gaps
- Not measured on staging (`mdx_asr_diarization_audio_ratio` p95) and not on in-house
  recordings — the gold set is public files, four two-speaker files per split.
- The 8 s roster floor does not transfer cleanly to v2 (it dissolves quiet real speakers:
  81 % vs 88 % exact on dev). Calibrate it per engine with in-house audio.


## Unreleased — Sprint 32: name suggestions, hardening, GA gate (GA: no)

### Added
- **Name suggestions (dark)**: rule-based self-introduction detection (en/de/uk, bounded
  patterns, table-tested, < 50 ms on 10 kB adversarial input) × calendar invitees
  (`domain/name_patterns.py`, `name_suggestions.py`); a match to exactly one invitee is required,
  the calendar spelling is offered with the quote as evidence. `name_suggestions` on the result
  (only when `MDX_NAME_SUGGESTIONS_ENABLED`, default **off** — the shadow run had 0 eligible jobs),
  `POST …/speakers/suggestions/dismiss`, accept via `PUT …/speakers` with source `suggestion`.
  Shadow script `scripts/ops/name_suggestion_shadow.py` (counts only, CI-guarded).
- **Re-label with the current engine**: `relabel_available` on the result (older engine, audio
  still stored — checked via a 10-min Redis cache; unknown → false), banner on web, iOS, macOS.
  `asr.rediarize_requested` gains `reason`.
- **Job erasure** (`domain/job_erasure.py`, `scripts/ops/erase_asr_job.py`): transcript + every
  `.r{n}` revision + audio + rows (edits cascade); tenant-scoped DELETE policies (migration 0048).
  DSAR runbook `docs/runbooks/asr-dsar.md`.
- Accessibility pass over every control added since Sprint 28 (web, iOS, macOS).
- `DiarizationEngineUnavailable` alert (+ `mdx_asr_diarization_unavailable_total`),
  `mdx_asr_name_suggestions_total`, `object_exists` / `exists` in libs/storage.
- Load harness `tests/load/diarization/` (staging) + in-process 2 h / 8-speaker run; report
  `docs/testing/load/speakers-2026-09-19.md`; capacity note in `docs/deploy/inventory.md`.
- ADR-0054 (legacy batch clusterer **kept** — removal precondition not met); GA checklist and
  debt list in `docs/product/speaker-decisions.md` — **GA: no** (gates 1–4, 7, 10 fail).

## Unreleased — Sprint 31: channel-aware capture on macOS

### Added
- **Call audio on macOS 14.2+**: a Core Audio process tap (excluding the app) in a private
  aggregate device with the microphone → one 2-channel 16 kHz file (ch0 mic, ch1 call audio).
  The remote side is recorded even with headphones. Blocking consent sheet (versioned), setting
  "Record call audio (other participants)", "You" / "Call audio" meters, a mode line that always
  says what is recorded, a menu-bar badge. Mic-only is the automatic fallback.
  **The go/no-go spike has not been run** — see ADR-0053 before enabling it for users.
- `POST /asr/jobs` takes `channel_layout=mic_system` (422 `channel_layout_mismatch` unless the file
  has 2 channels; a stereo file without the field behaves as before) and `local_speaker_name`
  (content: never logged or audited).
- Worker: stereo int16 decode, ASR once on the mixdown, **channel-aware diarization**
  (`libs/diarization/channels.py` + `dual_channel.py`): per-frame local/remote/both from VAD plus a
  loudspeaker leak model; each side diarized separately; a remote voice can never carry a local
  label. Any channel-path failure → mono on the mixdown (`mono_fallback`). Re-runs follow the
  layout. `DiarizationStats` gains `channel_layout`, `leak_gain_db`, `local_speakers`,
  `remote_speakers`, `both_share`.
- **Named from the channel** (ADR-0053, exception to ADR-0034): the only local speaker (≥ 10 s)
  gets the account owner's name, source `channel`, "from your microphone" with ✕ on web, iOS and
  macOS; clearing records `cleared`, carried through re-runs.
- Migration `0047_speaker_name_sources`; `PUT …/speakers` now persists `sources`. Result view:
  `speaker_sides`, `speaker_name_sources`.
- `run_der.py --dual` (+ mono A/B, side accuracy from `rttm/<id>.sides.json`),
  `mdx_asr_diarization_dual_jobs_total{outcome}`, dashboard panels, `DualChannelMonoFallbackHigh`
  alert with promtool tests, `channel_layout` dimension in the weekly speaker CSV.

### Fixed (found by the Sprint 30 gold replay)
- A calendar cap (`max_speakers`) could under-count: stray-chunk removal judged "dust" before the
  same-voice merge, dropping fragments of real far-field speakers. Dust is now judged after the
  merge, and a cap that the uncapped answer already fits returns that answer unchanged.

## Unreleased — Sprint 30: turn-level correction, learn loop, calendar context

### Added
- **Move turns** (`POST /asr/jobs/{id}/speakers/reassign`): one or several turns to another
  speaker, to a **new** speaker (the system missed someone; next free label, 8 live max) or to
  "Unknown". Optimistic concurrency on `result_rev` (409 `stale_result_rev`); undo via the
  latest-edit undo; **Reset speaker edits** (`POST …/speakers/edits/reset`). The artifact is
  never rewritten; edits fold in `seq` order with merges (docs/architecture/asr.md).
- Turn `segment_indices` are now in **artifact index space** (served segments carry
  `artifact_index` / `artifact_indices`), so a punctuation-only segment folded by NLP moves with
  its turn. Turns carry `uncertain` (overlap from the v2 engine, smoothed labels, absorbed
  unattributed speech); `overlap_ms` and per-segment `speaker_uncertain` are persisted.
- **Calendar context at capture**: `POST /asr/jobs` takes `name_candidates` (≤ 12 validated
  names) and `capture_source`; `X-Client-Type` lands in `capture_context`. Invitee counts are
  sent as `speakers_max` only; a person's "People" value always wins (the cap is dropped).
  Result view offers `name_candidates` as a rename picklist on web, iOS and macOS; naming
  source (`picklist`/`typed`) feeds `mdx_asr_speaker_named_total`.
- **Learn loop**: `result_first_read_at`, `mdx_asr_diarized_results_opened_total`,
  `mdx_asr_speaker_corrected_jobs_total`, weekly `speakers-YYYY-WW.csv` (`make
  weekly-speakers`) read through column-level grants for `funnel_reader`, metrics +
  decisions docs, opt-in eval export, correction-rate panel and alert.
- Migration `0045_speaker_context` (reassign shape, `creates_label`, candidates, capture
  context, first read). Audit kinds `asr.turn_reassigned`, `asr.speaker_edits_reset`.

### Changed
- `speakers_expected` + `speakers_max` together are no longer a 422: the person's count wins
  (`speakers_hint_invalid` retired).
- The PII log filter drops `speaker_names` / `name_candidates`.

## Unreleased — Sprint 29: diarizer v2 and the speaker-count control

### Added
- **Diarizer seam** (`libs/diarization/protocol.py`): `Diarizer` protocol + `DiarizationHints`
  (exact count / cap, 1–8). `LegacyEcapaDiarizer` is today's engine behind it
  (`DiarizationEngine` stays as an alias for dictation-service); `PyannoteDiarizer` runs
  pyannote `speaker-diarization-community-1` in-process from a digest-verified local
  directory, with telemetry forced off and the hub offline (it refuses to load otherwise).
  The worker keeps its word-level attribution unchanged.
- **Roster guard** for both engines (`roster.py`): a speaker under 8 s / 3 % of the speech is
  folded into the voice it resembles or left unattributed; off when a person stated the
  count. `count_confidence` (`high`/`low`) on `DiarizationStats` and the result view.
- **Speaker-count hints**: `POST /asr/jobs` takes `speakers_expected` / `speakers_max`
  (1–8); the legacy engine honours them too. Clients: "People: Auto · 1–5 · 6+" at capture
  on web, iOS and macOS (offline captures keep the hint).
- **Re-label speakers without re-transcribing**: `POST /asr/jobs/{id}/rediarize`
  (`{"speakers_expected": n|null}`) and `…/rediarize/undo` (one step). New labels come from
  the stored audio and words (no ASR pass), land in a new `….r{rev}.json.enc` artifact,
  carry names across on a clear majority, and leave the transcript readable throughout.
  Capped at 5 per job, one in flight, 10 per user per hour. "Wrong number of speakers?",
  progress, undo and a low-confidence banner on every client.
- Migration `0044_rediarize`: `diarization_status/error/runs/updated_at`,
  `previous_result_storage_uri`, `previous_speaker_names`; the reaper fails stranded
  re-runs (`stranded`) without touching the job.
- Engine switch `MDX_DIAR_ENGINE` (legacy default) and shadow mode
  `MDX_DIAR_SHADOW_ENGINE` (labels discarded, counts compared).
- Metrics `mdx_asr_diarization_audio_ratio`, `mdx_asr_diarization_shadow_delta`,
  `mdx_asr_rediarize_{total,seconds}`, `mdx_asr_rediarize_requests_total`; `engine` label on
  speakers/seconds. Dashboard panels and `DiarizationSlowVsAudio` /
  `RediarizeFailureRateHigh` alerts with promtool tests.
- Audit kinds `asr.rediarize_{requested,completed,failed,undone}`; `asr.job_queued` carries
  `speakers_hint` (vocabulary only).
- Eval: every engine through the production path, `guard_*` and `"hint": "oracle"` keys,
  `--label`; nightly `nightly-der.yml` + `compare_der.py` regression gate.

### Changed
- Transcript reads (result, presigned URL, merge) follow `result_storage_uri` instead of
  rebuilding the key from the job id.
- Merging speakers is refused (409 `rediarize_in_progress`) while a re-run is in flight.

### Deploy
- **asr-worker before asr-service** (an old worker acks a rediarize message as a no-op).
- `make migrate-up` (0044).

## Unreleased — Sprint 28: speaker truth baseline, guard-rails, merge

### Added
- **Merge speakers** on web, iOS and macOS: speaker roster with talk share, "Merge into…"
  from a speaker chip (two clicks), a prompt for a speaker who barely spoke, and undo for 10 s.
  The note's turn lines follow a merge; undo restores them unless the note was edited since.
- `POST /asr/jobs/{id}/speakers/merge` and `DELETE /asr/jobs/{id}/speakers/edits/{edit_id}`
  (undo, latest edit only). Edits are a reversible overlay folded in at read time; the stored
  transcript is never rewritten. `GET …/result` gains `speaker_stats`, `result_rev`, `edits`.
- Migration `0043_speaker_edits`: `transcription_speaker_edits` (RLS) and
  `transcription_jobs.diarization_rev`.
- `metadata.diarization` (`DiarizationStats`) on every diarized job: engine, chunks, clusters
  raw / after merge / dropped, speakers, speech per speaker, unknown share, wall time.
- Metrics `mdx_asr_diarization_{speakers,seconds,unknown_share}`,
  `mdx_asr_diarization_clusters_dropped_total`, `mdx_asr_speaker_edits_total`; "Speakers" row in
  the ASR dashboard; `DiarizationSpeakerOvercount` alert with a promtool test.
- Audit kinds `asr.speakers_merged`, `asr.speaker_edit_reverted` (labels only).
- Speaker gold set `eval/speakers/v1` (manifest + RTTMs; audio fetched, never committed),
  `make der-eval`, `make der-grid`, `make sim-overcount`, `make check-no-eval-audio` (CI),
  pyannote community-1 bake-off adapter, consent template and erase script.
- Clusterer knobs `min_speaker_speech_ms`, `cluster_chunk_min_ms` and a Silero `threshold`
  pass-through, all off by default (behaviour unchanged).

### Measured (gold set: AMI 8 meetings × 2 mics + VoxConverse 16 files; `docs/eval/grid-2026-09-19-legacy.json`)
- Legacy baseline, test split (16 files): count exact 44 %, over-count 50 %, under-count 6 %,
  DER 0.38.
- B-4 grid winner (speech ≥ 5 s, share ≥ 2 %, 3 s chunks, clustering chunks ≥ 1 s, merge 0.45):
  count exact 88 %, over-count 0 %, DER 0.29, but under-count 12.5 % (a 4- and a 5-speaker file).
  **Not shipped**: the pre-registered rule caps under-count at 5 % of files (the baseline
  already misses that cap). On the eight 2-speaker VoxConverse files it was 8/8 exact vs 3/8.
