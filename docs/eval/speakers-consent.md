# Speaker gold set — consent

Every voice in an in-house recording signs before recording. No consent, no file.

## Template (one per person, per recording session)

> I agree that my voice is recorded for the Notes AI speaker-labelling test set.
> The recording is stored in a private bucket, used only to measure speaker
> labelling, never sent to a third-party service, and never used to identify me.
> I can ask for it to be deleted at any time; it is then removed within 7 days.
>
> Name · Date · Recording ids · Signature

## Register

Product recordings exported with `scripts/ops/export_job_for_eval.py`
(Sprint 30, `docs/runbooks/speakers-eval.md`) list the job as `job:<job-uuid>`
in "recording ids" before the export, and the printed `export_id` after it.

| consent_ref | recording ids | people | date | withdrawn |
|---|---|---|---|---|
