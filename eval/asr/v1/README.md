# ASR gold set `eval/asr/v1` (Sprint TQ1)

Real recordings with human-corrected transcripts, scored by
`scripts/eval/asr_eval.py` against the criteria TR-01 to TR-13
(`scripts/eval/taxonomy.py`).

**Only this README and `manifest.json` are in git.** Everything else is
personal data or third-party content and lives in the private eval bucket.
CI fails on any other tracked file under `eval/asr/**`
(`scripts/ci/check-no-eval-audio.sh`).

## Layout

```
eval/asr/v1/
  manifest.json          # git: ids, language, kinds, minutes, split, consent_ref | licence
  README.md              # git
  <id>/                  # local only, fetched from s3://notes-eval/asr/v1/<id>/
    audio.<ext>          # original bytes
    reference.json       # [{start_ms, end_ms, speaker, text, language}], verbatim-lite
    spans.json           # entities, numbers/dates, non_speech regions, code_switch regions
    reference.rttm       # speaker turns for the DER harness
    alignment.json       # forced alignment of the reference, cached (TR-08)
```

Formats are the pydantic models in `scripts/eval/asr_gold.py`; the labelling
rules (verbatim-lite) are encoded in `scripts/eval/asr_scoring.py`.

## Fetch (eval role)

```bash
# eval role credentials in the environment, as for fetch_speaker_corpus.py
uv run python scripts/eval/asr_gold.py fetch eval/asr/v1
make eval-asr-validate                      # manifest, composition, local content
```

`MDX_EVAL_ASR_URI` overrides the bucket prefix. It must still be an
`…eval…/asr/v1` prefix, or the fetch refuses.

## Add a recording

1. **Consent first.** Every voice signs the template in
   `docs/eval/speakers-consent.md`. The register row gets the next `C-YYYY-NNN`.
   A public-domain recording states its licence and sets `public: true`
   instead. A third-party broadcast kept for internal eval (r03, r04) states
   its basis in `licence`.
2. **Upload** the original bytes to `s3://notes-eval/asr/v1/<id>/audio.<ext>`.
   Product recordings go through `scripts/ops/export_job_for_eval.py`.
3. **Draft** the reference from the in-process backend's output:
   `make eval-asr BACKEND=inproc_cpu_asr IDS=<id> DRAFT=1` writes
   `scripts/eval/local/asr-draft/<id>.reference.json`.
4. **Correct** it from the audio. Two passes by different people on the
   test split. Mark the spans. Set `reference_passes` in the manifest.
5. **Upload** `reference.json`, `spans.json` and `reference.rttm` to the
   bucket and commit only the manifest row.
6. `make eval-asr-validate` shows 0 problems for the new row.

Split is `dev` or `test` and is fixed forever once set. Tune on `dev` only.

## Erase

```bash
uv run python scripts/ops/erase_eval_recording.py <id>
```

This removes the bucket prefix, the local folder and the manifest row. Record
the erasure in the consent register.
