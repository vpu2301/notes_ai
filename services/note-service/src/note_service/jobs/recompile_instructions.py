"""Recompile the meeting-type note instructions after the workspace text changed (N4).

A type text is compiled together with the workspace text, so a new workspace version makes
every type row ``stale``; until this job has run, the worker writes with the workspace row
instead. One tenant block per row; a crash mid-way leaves the remaining rows ``stale``,
which is safe, and the job is retried. Counts only, never a text.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final
from uuid import UUID

from db import tenant_connection

from ..domain import note_instructions as ni
from ..domain import note_instructions_compiler as compiler
from ..domain import note_instructions_repository as repo

logger = logging.getLogger(__name__)

JOB_KIND: Final = "note.instructions_recompile"
MAX_ATTEMPTS: Final = 3


def idempotency_key(workspace_version: int) -> str:
    """One job per workspace version; a newer version enqueues a new one."""
    return f"recompile:{workspace_version}"


async def handle_recompile(
    deps: Any, *, tenant_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """``deps.app_pool`` and ``deps.compiler_for(tenant_id) -> provider``."""
    del payload  # {"scope": "*"}: every stale type row
    started = time.monotonic()
    async with tenant_connection(deps.app_pool, tenant_id) as conn:
        rows = await repo.fetch_many(conn, tenant_id=tenant_id, scopes=repo.SCOPES)
    workspace = rows.get(repo.WORKSPACE)
    stale = [rows[s] for s in repo.TYPE_SCOPES if s in rows and rows[s].stale]
    if not stale:
        return {"recompiled": 0, "failed": 0}
    provider = await deps.compiler_for(tenant_id)
    done = failed = 0
    for row in stale:
        parent = workspace.text if workspace is not None else ""
        result = await compiler.compile_text(compiler.join([parent, row.text]), provider=provider)
        async with tenant_connection(deps.app_pool, tenant_id) as conn:
            await repo.set_compiled(
                conn,
                tenant_id=tenant_id,
                scope=row.scope,
                profile=result.profile.model_dump(mode="json"),
                profile_hash=ni.canonical_hash(result.profile),
                compile_status=result.status,
                compile_error_kind=result.error_kind,
                compiler_version=compiler.COMPILER_VERSION,
                backend=result.backend,
                base_versions={repo.WORKSPACE: workspace.version} if workspace is not None else {},
            )
        done += result.status == "compiled"
        failed += result.status != "compiled"
    seconds = round(time.monotonic() - started, 2)
    logger.info(
        "note_instructions.recompiled",
        extra={
            "tenant_id": str(tenant_id),
            "rows": len(stale),
            "failed": failed,
            "seconds": seconds,
        },
    )
    return {"recompiled": done, "failed": failed, "seconds": seconds}
