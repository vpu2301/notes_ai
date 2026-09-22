# Load and failure drills — note generation (Sprint 37 B-5)

Scenarios are defined once, in `tests/load/note_generation/scenarios.py`,
so the runner, this page and the GA checklist cannot drift. Seven of them;
two run on a dev database, five need a deployed stack with a real model
backend.

## Runs on any machine

    make dev-up && make migrate-up
    RUN_NOTE_LOAD=1 uv run --project libs/jobs pytest tests/load/note_generation/runner.py -v

* **noisy_neighbour** — 50 generations from one workspace, 1 from another;
  the single job must be claimed within the first two rounds.
* **per-workspace cap** — 20 queued from one workspace; at most
  `MDX_NOTE_GENERATION_PER_TENANT` in flight (soft: see migration 0055).

## Needs a deployed stack

Run against **staging**, with the note-worker replica count pinned to 1 so
the numbers mean something:

| Scenario | How | Pass |
|---|---|---|
| `burst` | enqueue 30 generations (10× 30 min, 10× 60 min, 10× 90 min) via `POST /v1/notes/from-transcript` on a seeded workspace | p95 for a 60-minute meeting ≤ 3 min from the start of its turn; note API p95 within 10 % of the idle baseline |
| `cold_backend` | scale the HF endpoint to zero, enqueue one | jobs park as `waiting_on_model`, recover unattended; report the first-job penalty |
| `backend_5xx` | fault-inject 5xx for 10 min in front of the backend | retries follow `retry_backoff_seconds`; none lost, none duplicated |
| `worker_killed` | `kubectl delete pod` at each step (extract / write #1 / reduce / write #2) | exactly one version per write step; `note_generated_items` consistent with it |
| `autosave_storm` | 200 autosaves/min on a note while it generates | no user text lost; ≤ 5 writer retries |

`budget_reached` is covered by unit tests (`test_ai_settings.py`) and by
the `burst` run on a workspace whose budget is set below the run's cost.

## Reporting

One row per scenario in `docs/testing/load/notes-<date>.md` with the
measured numbers from `Scenario.measures`, the environment, the worker
replica count and the backend. A scenario that could not be run is
recorded as **not run**, never as a pass. The capacity line
(meeting-hours per day per worker replica per tier) goes in
`docs/deploy/inventory.md`.

**No run has been recorded yet.** The scenarios and the two local drills
were written on 2026-09-20; the rest need a staging deployment with a
chat backend.
