-- Workspaces & invitations (W2, ADR-0070): the funnel cohort.
--
-- One row per ISO week of workspace creation, counts only:
--   self-serve team workspaces created → with ≥1 invitation → invitations
--   sent → accepted → accepted within 24 h → invitees who wrote a note in
--   that workspace within 24 h of accepting.
--
-- Run as `funnel_reader` (0040, 0072: no address or message is readable).
-- "Has an account" is not derivable here without reading identities; the
-- split lives in Prometheus (`mdx_auth_invitation_total{has_account}`).

WITH workspaces AS (
    SELECT id, created_at, date_trunc('week', created_at)::date AS week
    FROM tenants
    WHERE kind = 'team' AND signup_source = 'self_serve'
),
invites AS (
    SELECT i.id, i.tenant_id, i.created_at, i.accepted_at, i.accepted_by, i.sent_count
    FROM tenant_invitations i
    JOIN workspaces w ON w.id = i.tenant_id
    WHERE i.note_id IS NULL
),
first_note AS (
    SELECT i.id AS invitation_id
    FROM invites i
    JOIN notes n ON n.tenant_id = i.tenant_id
                AND n.primary_author_id = i.accepted_by
                AND n.created_at BETWEEN i.accepted_at AND i.accepted_at + interval '24 hours'
    GROUP BY i.id
)
SELECT
    w.week,
    count(DISTINCT w.id)                                              AS workspaces_created,
    count(DISTINCT i.tenant_id)                                       AS workspaces_inviting,
    count(DISTINCT i.id) FILTER (WHERE i.sent_count > 0)              AS invitations_sent,
    count(DISTINCT i.id) FILTER (WHERE i.accepted_at IS NOT NULL)     AS invitations_accepted,
    count(DISTINCT i.id) FILTER (
        WHERE i.accepted_at <= i.created_at + interval '24 hours')    AS accepted_within_24h,
    count(DISTINCT f.invitation_id)                                   AS first_note_within_24h
FROM workspaces w
LEFT JOIN invites i ON i.tenant_id = w.id
LEFT JOIN first_note f ON f.invitation_id = i.id
GROUP BY w.week
ORDER BY w.week DESC;
