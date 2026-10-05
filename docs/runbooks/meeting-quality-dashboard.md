# Runbook — the admin "Meeting quality" dashboard

**What it is.** After each real recording, an admin can see how the transcript and the note went.
It is a Grafana dashboard, `Notes AI › Meeting quality (admin)`, uid `meeting-quality`. It is not part
of the product, and no user-facing route links to it.

## Open it (dev)

```bash
make dev-up                       # or: docker compose up -d postgres grafana
open http://localhost:3001/d/meeting-quality
```

Sign in as `admin` / `admin`. Grafana has sign-up off and anonymous access off, and it listens on
`127.0.0.1` only. A user account of the product cannot sign in to Grafana at all.

## What one row shows

| Part | Columns | Source |
|---|---|---|
| Recording | Finished, Note (code), Workspace, ASR status, minutes, language, ASR model, RTF | `transcription_jobs`, `quality` |
| Transcript | Coverage, Confidence, low-confidence words, speakers, unknown-speaker share | `quality` (worker, on completion) |
| Guards | Dropped segments, prompt echo, backend errors | `quality` |
| Spellings | Unified names accepted / proposed / rejected | `transcript_corrections` (status only) |
| Note | Status, writer, writer model, prompt version, seconds, facts, key points, facts by third, unsupported lines, open lint findings, recording type, error | latest `note_generations` row |

Trend panels plot the same numbers per recording over time. Two tables count spelling decisions by
source and failures by stage and error kind.

## Numbers only

Every query runs as `funnel_reader`. Its column grants (migrations 0046, 0060 and 0067) stop at
metadata. It cannot select a transcript, a note's text or title, a speaker name, a spelling, the
vocabulary hint or an error message. The worker's summary (`services/asr-worker/src/asr_worker/quality.py`)
holds counts, shares, seconds, language codes and enum reasons only. Tests enforce both rules:
`tests/unit/test_meeting_quality_dashboard.py`, `services/asr-worker/tests/unit/test_quality_summary.py`,
and `tests/integration/test_meeting_quality_grants.py` (`RUN_DB_INTEGRATION=1`).

To see what was actually said, open the note in the product as a member of its workspace.

## Older recordings

Jobs that completed before migration 0067 have no summary. Fill them once:

```bash
make meeting-quality-backfill                 # dry run: how many jobs
make meeting-quality-backfill ARGS=--apply    # write
```

The script reads each transcript through the worker's decrypt path, so it needs the worker's
settings. On a dev Mac with the stack's containers stopped, export the worker's DSNs and S3 settings
with `localhost` hosts and set `MDX_MASTER_KEY_PATH=$PWD/infra/dev/master.key`. Only rows whose
`quality` is NULL are written, and backfilled rows carry `"backfilled": true`.

## Changing the dashboard

Edit the SQL in `scripts/grafana/build_meeting_quality_dashboard.py`, then run
`make meeting-quality-dashboard`. The unit test fails when the JSON and the generator disagree.
A new column needs a column-level `GRANT SELECT (...) ... TO funnel_reader` in a migration, and it
must not be content.

## Staging and production

`admin` / `admin` is a dev default only (`docker-compose.yml`). Production Grafana is the
kube-prometheus-stack one (`docs/deploy/observability.md`):

- set its admin password from a secret, never the chart default;
- keep sign-up and anonymous access off, and keep it off the public ingress (port-forward or SSO);
- add the `funnel` Postgres datasource with a rotated `funnel_reader` password, not `funnel_reader`;
- mount `meeting-quality.json` like the other dashboards (`grafana_dashboard: "1"` ConfigMap).
