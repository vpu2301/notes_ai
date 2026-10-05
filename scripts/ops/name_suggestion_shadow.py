"""Name-suggestion shadow run (Sprint 32 B-2) — counts only, no UI.

    # in the cluster, with the asr-service environment (DB, S3, master key):
    uv run --project services/asr-service python scripts/ops/name_suggestion_shadow.py --days 30

For every completed job of the last ``--days`` that has calendar name
candidates AND at least one speaker a person named (source typed or
picklist), compute suggestions with the endpoint's suggestion code on the
structured turns (decrypt → edits folded → ``name_suggestions.suggest``)
with the person's names hidden — on the raw transcript text, WITHOUT the
NLP enrichment the endpoint adds (that needs a user bearer) — then compare
with what they actually chose:

    offered   labels a suggestion was made for
    agree     the suggestion equals the person's name (normalised)
    disagree  the person named that speaker something else
    unnamed   the person never named that speaker (not scored)

precision = agree / (agree + disagree), per language. Decision rule
(docs/product/speaker-decisions.md): ≥ 95 % with ≥ 100 compared labels →
enable; 85–95 % → pilots only; < 85 % → stays dark.

It reads transcript text, so it prints ONE JSON line of counts and nothing
else; `tests/unit/test_name_suggestion_shadow.py` fails the build if any
other output call appears. Tenants come from `funnel_reader` (tenant ids
of calendar-event captures only); each tenant is read inside its own
`tenant_connection`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from typing import Any
from uuid import UUID

COMPARED_SOURCES = {"typed", "picklist"}


def _norm(name: str) -> str:
    return " ".join(name.casefold().split())


def score(suggestions: list[Any], names: dict[str, str], sources: dict[str, str]) -> dict[str, int]:
    """Counts for one job. Pure — tested without a database."""
    out = {"offered": 0, "agree": 0, "disagree": 0, "unnamed": 0}
    for s in suggestions:
        out["offered"] += 1
        chosen = names.get(s.label)
        if not chosen or sources.get(s.label) not in COMPARED_SOURCES:
            out["unnamed"] += 1
        elif _norm(chosen) == _norm(s.name):
            out["agree"] += 1
        else:
            out["disagree"] += 1
    return out


def _emit(report: dict[str, Any]) -> None:
    """The ONLY output of this script: counts."""
    print(json.dumps(report, sort_keys=True))


async def _tenants(days: int) -> list[UUID]:
    import asyncpg

    conn = await asyncpg.connect(os.environ["DB_FUNNEL_READER_DSN"])
    try:
        rows = await conn.fetch(
            """
            SELECT DISTINCT tenant_id FROM transcription_jobs
            WHERE status = 'complete' AND finished_at > now() - make_interval(days => $1)
              AND capture_context->>'source' = 'calendar_event'
            """,
            days,
        )
    finally:
        await conn.close()
    return [r["tenant_id"] for r in rows]


async def main(days: int) -> int:
    import logging

    # Nothing but the one counts line may leave this process: service
    # libraries log, and a failed parse would print transcript snippets.
    logging.disable(logging.CRITICAL)
    from asr_models import TranscriptionOutput
    from asr_service.domain import repository
    from asr_service.domain.name_suggestions import suggest
    from asr_service.main_deps import build_state, teardown_state
    from asr_service.routers.jobs import _edit_view, _load_transcript
    from db import tenant_connection

    state = await build_state()
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"jobs": 0, "offered": 0, "agree": 0, "disagree": 0, "unnamed": 0}
    )
    skipped = 0
    try:
        for tenant_id in await _tenants(days):
            async with tenant_connection(state.app_pool, tenant_id) as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, diarization_rev, result_storage_uri, speaker_names,
                           speaker_name_sources, speaker_name_candidates
                    FROM transcription_jobs
                    WHERE status = 'complete'
                      AND finished_at > now() - make_interval(days => $1)
                      AND jsonb_array_length(speaker_name_candidates) > 0
                      AND speaker_names <> '{}'::jsonb
                    """,
                    days,
                )
            for row in rows:
                names = repository.parse_speaker_names(row["speaker_names"])
                sources = repository.parse_speaker_names(row["speaker_name_sources"])
                if not any(v in COMPARED_SOURCES for v in sources.values()):
                    continue
                candidates = json.loads(row["speaker_name_candidates"])
                async with tenant_connection(state.app_pool, tenant_id) as conn:
                    edits = await repository.list_speaker_edits(
                        conn, job_id=row["id"], result_rev=int(row["diarization_rev"])
                    )
                try:
                    raw = await _load_transcript(
                        state, tenant_id, row["id"], row["result_storage_uri"]
                    )
                    output = TranscriptionOutput.model_validate_json(raw)
                    view = _edit_view(row["id"], output, {}, edits)  # names hidden on purpose
                    job_counts = score(
                        suggest(
                            view.turns,
                            language=output.language,
                            candidates=candidates,
                            custom_names={},
                        ),
                        names,
                        sources,
                    )
                except Exception:  # noqa: BLE001 — erased/unreadable: counted, never shown
                    skipped += 1
                    continue
                bucket = totals[output.language]
                bucket["jobs"] += 1
                for k, v in job_counts.items():
                    bucket[k] += v
    finally:
        await teardown_state(state)
    report: dict[str, Any] = {"days": days, "by_language": dict(totals), "skipped": skipped}
    compared = sum(b["agree"] + b["disagree"] for b in totals.values())
    agree = sum(b["agree"] for b in totals.values())
    report["compared"] = compared
    report["precision"] = round(agree / compared, 4) if compared else None
    _emit(report)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=30)
    sys.exit(asyncio.run(main(parser.parse_args().days)))
