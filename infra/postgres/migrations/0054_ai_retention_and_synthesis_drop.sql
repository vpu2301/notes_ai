-- 0054 — Sprint 37: what the AI path leaves behind, and what it stops
-- leaving behind.
--
-- Three retention holes and one piece of dead weight:
--
-- 1. `model_usage` was documented as 400-day (0023 header) with no sweep
--    to make that true, and its DELETE policy is `USING (false)` on
--    purpose — an append-only ledger the application cannot rewrite. The
--    sweep therefore needs a role that is not the application: the same
--    reasoning 0029 used for `auth_sessions`.
-- 2. `jobs` rows are history with ids in them, kept forever. Terminal
--    rows older than 30 days are noise that slows every queue scan.
-- 3. `model_usage_monthly` (0053) was created without
--    `security_invoker`, which in Postgres means it runs as its OWNER and
--    ignores the caller's RLS on `model_usage`. The route filters by
--    tenant, so nothing leaked, but a view that is only safe because of
--    the query above it is not safe. Fixed here.
--
-- And the synthesis stub (debt D-2): `note_synthesis_jobs` backed
-- `POST /v1/notes/{id}/synthesize`, a vendor-specific path outside the
-- provider seam that the document engine (Sprint 33) replaced. No client
-- calls it. The code goes with this migration.

-- ── 1 + 2: a role that may forget things ────────────────────────────
-- `tenant_writer` already holds the "scheduled maintenance" grants
-- (0029). It gains no read of note content here: both tables hold ids,
-- counts and costs.

CREATE POLICY model_usage_retention_select ON model_usage
    FOR SELECT TO tenant_writer USING (true);
CREATE POLICY model_usage_retention_delete ON model_usage
    FOR DELETE TO tenant_writer USING (true);
GRANT SELECT, DELETE ON model_usage TO tenant_writer;

CREATE POLICY jobs_retention_select ON jobs
    FOR SELECT TO tenant_writer USING (true);
CREATE POLICY jobs_retention_delete ON jobs
    FOR DELETE TO tenant_writer
    -- Terminal only. A queued or running job is never retention.
    USING (status IN ('complete', 'failed', 'dead', 'cancelled'));
GRANT SELECT, DELETE ON jobs TO tenant_writer;

-- ── 3: the month-to-date view obeys the caller's RLS ────────────────
ALTER VIEW model_usage_monthly SET (security_invoker = true);

-- ── D-2: the synthesis stub ─────────────────────────────────────────
DROP TABLE IF EXISTS note_synthesis_jobs;
