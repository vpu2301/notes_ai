# Changelog

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
