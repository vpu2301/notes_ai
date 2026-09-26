-- 0055 — Sprint 37 B-3: one workspace cannot take the whole queue.
--
-- `jobs_claim` is FIFO by (priority, run_at). That is right for a queue
-- of equals and wrong for a shared one: a workspace that uploads fifty
-- recordings puts fifty jobs ahead of everybody else's single meeting,
-- and the person waiting for that one note waits for all fifty. With a
-- 60-minute meeting taking minutes to write, "wait your turn" is an hour.
--
-- Two changes, both inside the claim:
--
-- * **Round-robin by workspace.** Rank each workspace's queued jobs and
--   order by rank BEFORE run_at, so the first round takes one job from
--   every waiting workspace. The fifty still run; they run interleaved.
-- * **A per-workspace in-flight cap.** A workspace already running
--   `per_tenant` jobs claims nothing more until one finishes. This is
--   what stops a single tenant occupying every worker replica.
--
-- Priority still wins over both: a person pressing Regenerate is on the
-- screen waiting, and that outranks fairness between background uploads.
--
-- The cap is a soft one, and deliberately: two workers claiming at the
-- same instant each see the other's rows only once they commit, so a
-- workspace can briefly exceed it by a claim's worth. Making it exact
-- would mean serialising every claim on a per-tenant lock, which costs
-- more than the thing it prevents — the cap exists to stop one workspace
-- occupying a fleet for minutes, not to be an accounting boundary.
--
-- The old `jobs_claim` stays for callers that have no fairness question
-- (one tenant per deployment, or a queue of one kind).

CREATE OR REPLACE FUNCTION jobs_claim_fair(
    kinds          TEXT[],
    worker         TEXT,
    lease_seconds  INTEGER,
    max_rows       INTEGER,
    per_tenant     INTEGER
)
RETURNS SETOF jobs
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    WITH in_flight AS (
        SELECT tenant_id, count(*) AS running
          FROM jobs
         WHERE status = 'running' AND kind = ANY (kinds)
         GROUP BY tenant_id
    ),
    eligible AS (
        SELECT c.id,
               c.priority,
               c.run_at,
               row_number() OVER (
                   PARTITION BY c.tenant_id
                   ORDER BY c.priority DESC, c.run_at
               ) AS rank_in_tenant,
               -- How many MORE this workspace may run. Counting only the
               -- rows already running would let a claim of two take the
               -- workspace from two in flight to four.
               per_tenant - coalesce(f.running, 0) AS headroom
          FROM jobs c
          LEFT JOIN in_flight f ON f.tenant_id = c.tenant_id
         WHERE c.status IN ('queued', 'waiting_on_model')
           AND c.run_at <= now()
           AND c.kind = ANY (kinds)
           AND coalesce(f.running, 0) < per_tenant
    )
    UPDATE jobs j
       SET status           = 'running',
           attempts         = CASE WHEN j.status = 'waiting_on_model' THEN j.attempts ELSE j.attempts + 1 END,
           leased_by        = worker,
           lease_expires_at = now() + make_interval(secs => lease_seconds),
           heartbeat_at     = now(),
           started_at       = COALESCE(j.started_at, now())
     WHERE j.id IN (
           SELECT e.id FROM eligible e
            WHERE e.rank_in_tenant <= e.headroom
            ORDER BY e.priority DESC, e.rank_in_tenant, e.run_at
            LIMIT max_rows
              FOR UPDATE SKIP LOCKED)
    RETURNING j.*;
$$;

GRANT EXECUTE ON FUNCTION jobs_claim_fair(TEXT[], TEXT, INTEGER, INTEGER, INTEGER) TO app_role;
