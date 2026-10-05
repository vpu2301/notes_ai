# Eval

## Speaker gold set (`eval/speakers/v1`)

Manifest + RTTMs in git; audio never (CI: `make check-no-eval-audio`).

```
uv run python scripts/eval/fetch_speaker_corpus.py          # audio → eval/speakers/v1/audio/, sha256-checked
make der-eval ENGINE=legacy SPLIT=test                       # → docs/eval/der-<date>-<engine>-<split>.json
make der-grid                                                # B-4 grid on dev, ship/no-ship on test
make sim-overcount                                           # no-audio clusterer regression
```

- Manifest fields: `id, source (inhouse|ami|voxconverse), license, consent_ref,
  language, condition, client, n_speakers, duration_s, audio_sha256, audio_uri,
  rttm (null = count-only), split (dev|test, fixed)`. Tune on `dev` only.
- Conditions: `room_laptop_mic, call_speaker_bleed, headset_solo, headset_mix,
  iphone_table, web_opus, farfield_array, broadcast`.
- Public today: AMI (8 meetings × headset mix + far-field array, 4 speakers) and
  VoxConverse dev (16 files, 1–5 speakers, 8 of them 2-speaker). In-house files are added
  as they are recorded and consented.
- In-house recordings: consent first (`docs/eval/speakers-consent.md`), recorded
  with our clients, original bytes to `s3://notes-eval/speakers/v1/` (private,
  eval role). Annotate in Audacity, then
  `scripts/eval/labels_to_rttm.py <id> labels.txt > eval/speakers/v1/rttm/<id>.rttm`.
  Erase on request: `scripts/ops/erase_eval_recording.py <id>`.
- Product recordings (`eval/speakers/v2`, Sprint 30): opt-in, one consented
  job at a time via `scripts/ops/export_job_for_eval.py` →
  `s3://notes-eval/speakers/v2/`, audited as `asr.audio_exported_for_eval`.
  The erase script covers v2 too.
- Metrics: count exact / ±1 / over / under, DER collar 0 with overlap (headline),
  DER collar 0.25 without overlap, JER, unknown share, extra-speaker share, RTF.
- Bake-off: `--engine 'pyannote_c1:{"max_speakers": 8}'` with
  `uv run --with 'pyannote.audio>=4.0,<4.1' --with 'pyannote.metrics>=4,<5'`
  (pyannote.audio 4 requires metrics 4; scores match 3.2 — checked on
  `vc-crixb`, legacy + guard DER 0.270 under both); model fetched once into
  `~/.cache/mdx-models/speaker-diarization-community-1` (gated, CC-BY-4.0).
  The adapter forces `PYANNOTE_METRICS_ENABLED=false` and `HF_HUB_OFFLINE=1`.


## ASR gold set (`eval/asr/v1`, Sprint TQ1)

Real recordings with human-corrected transcripts, used for the transcript
criteria TR-01 to TR-13. Only `manifest.json` and `README.md` are in git.
References, spans, RTTM, alignment and audio live in
`s3://notes-eval/asr/v1/<id>/` (eval role). CI fails on tracked content
under `eval/asr/**` and `eval/notes/**`.

```
uv run python scripts/eval/asr_gold.py fetch eval/asr/v1   # eval role
make eval-asr-validate                                      # manifest, composition, content
make eval-asr BACKEND=inproc_cpu_asr SPLIT=test             # → docs/eval/asr-<date>-<backend>-<split>.{json,md}
make eval-asr-assert                                        # r03/r04 checklists (XFAIL = a later sprint's)
make der-eval ENGINE=pyannote_c1 SPLIT=test CORPUS=eval/asr/v1   # de/uk DER on the same recordings
```

- Every recording goes through `asr_worker.processor.decode_recording`, the
  job's own path, on the backend named in `config/models.yaml`.
- The labelling rules (verbatim-lite) are encoded in `scripts/eval/asr_scoring.py`;
  formats are the pydantic models in `scripts/eval/asr_gold.py`.
- The metrics are in `scripts/eval/asr_scoring.py`. Each maps to a taxonomy
  code, and `test_notes_gates.py` enforces that.
- The nightly workflow `nightly-asr.yml` compares each backend to
  `docs/eval/asr-baseline-<backend>-test.json`. Per language, WER may rise
  at most 1.0 pp, and TR-02/TR-03 may not worsen (ADR-0019 amendment).

## Sprint 29 — engines behind the seam, guard, user-stated count

Both engines run through the production code path: `legacy` via
`diarize_embeddings`, `pyannote_c1` via `diarization.pyannote_engine`
(`extract` → `to_diarization`, the mapping the worker stores). Keys every
engine accepts:

```
--engine 'legacy:{"guard_speech_ms": 8000, "guard_share": 0.03}'    # roster guard (MDX_DIAR_MIN_SPEAKER_*)
--engine 'pyannote_c1:{"hint": "oracle"}'                             # gold count as a person-stated count (E2)
--label legacy-guard                                                  # report name; without it the engine name is used
```

Always pass `--label` for a non-default config: reports are named
`der-<date>-<label>-<split>.json` and a second run on the same day
overwrites the first.

- Nightly (`.github/workflows/nightly-der.yml`, self-hosted `mdx-eval` Mac):
  both engines on `test`, then `scripts/eval/compare_der.py` fails the run if
  `count_exact` on 2-speaker files drops > 5 points against
  `docs/eval/der-baseline-<engine>-test.json`. Refresh a baseline in a PR,
  with the report, only when a change is meant to move the numbers.
