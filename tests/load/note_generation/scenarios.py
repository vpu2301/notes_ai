"""The seven note-generation drills (Sprint 37 B-5), as data.

Each scenario is a name, what it does to the system, and the bar it has
to clear. They are in code rather than only in a document because the
runner, the report and the GA checklist must be reading the same numbers:
a pass bar that lives in prose drifts from the one that was measured.

Running them needs a deployed stack with a real model backend, so
`runner.py` is skipped unless ``RUN_NOTE_LOAD=1``. Results are written to
``docs/testing/load/notes-<date>.md`` with one row per scenario.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final


@dataclass(frozen=True, slots=True)
class Scenario:
    key: str
    """What is done to the system, in one sentence."""
    load: str
    """What must be true afterwards. Binary — no "looks fine"."""
    passes_if: str
    """What the runner has to be able to do to the environment. A drill
    nobody can set up is a drill nobody runs."""
    needs: tuple[str, ...] = ()
    measures: tuple[str, ...] = field(default_factory=tuple)


SCENARIOS: Final[tuple[Scenario, ...]] = (
    Scenario(
        key="burst",
        load="30 generations queued at once (mixed 30/60/90-minute meetings), one worker replica",
        passes_if="p95 for a 60-minute meeting ≤ 3 min from the moment its turn starts; "
        "no note API latency change greater than 10 %",
        measures=("queue_drain_seconds", "p95_generation_seconds", "api_p95_delta_pct"),
    ),
    Scenario(
        key="cold_backend",
        load="model backend scaled to zero, then one generation enqueued",
        passes_if="jobs park as waiting_on_model and recover with no manual action",
        needs=("a backend that can be scaled to zero",),
        measures=("first_job_penalty_seconds",),
    ),
    Scenario(
        key="backend_5xx",
        load="backend returns 5xx for 10 minutes",
        passes_if="jobs retry per retry_backoff_seconds; none lost, none run twice",
        needs=("a fault-injecting proxy in front of the backend",),
        measures=("retries", "lost", "duplicated"),
    ),
    Scenario(
        key="worker_killed",
        load="worker killed at each step in turn: extract, write #1, reduce, write #2",
        passes_if="exactly one version per write step and items consistent with it",
        measures=("versions_per_step", "orphan_items"),
    ),
    Scenario(
        key="autosave_storm",
        load="200 autosaves/min on a note while it is being generated",
        passes_if="no user text lost (property check) and at most 5 writer retries",
        measures=("lost_characters", "writer_retries"),
    ),
    Scenario(
        key="noisy_neighbour",
        load="one workspace enqueues 50 generations, another enqueues 1",
        passes_if="the single job starts within 2 minutes",
        measures=("single_job_wait_seconds",),
    ),
    Scenario(
        key="budget_reached",
        load="a workspace crosses its monthly budget mid-run",
        passes_if="the generation is refused with budget_exceeded, the note still works, "
        "and exactly one notification is produced for the month",
        measures=("notifications", "notes_broken"),
    ),
)

BY_KEY: Final[dict[str, Scenario]] = {s.key: s for s in SCENARIOS}
