-- Recipient viral loop — the funnel cohort (Sprints 19–22).
--
-- One row per ISO week of link creation, counts only:
--   finalized notes → notes with a recipient link → links created → sent
--   by the product → first-viewed → with ≥1 response → CTA clicked →
--   leads → referred signups → verified workspaces → workspaces with a
--   finalized note within 7 days of verifying.
--
-- Run as `funnel_reader` (migration 0040) — Grafana's Postgres datasource
-- and scripts/jobs/weekly_funnel.py both do. The join from referrals to
-- the sender's link happens HERE and nowhere in the product: no table
-- stores the referring tenant next to the referred one.

WITH weeks AS (
    SELECT date_trunc('week', created_at)::date AS week, id AS note_id
    FROM notes WHERE finalized_at IS NOT NULL AND deleted_at IS NULL
),
links AS (
    SELECT id, note_id, ref_code, created_at,
           date_trunc('week', created_at)::date AS week,
           first_viewed_at, cta_clicked_at,
           delivery_status::text AS delivery_status
    FROM note_share_links
    WHERE kind = 'recipient'
),
responded AS (
    SELECT DISTINCT link_id FROM share_link_responses WHERE cleared_at IS NULL
),
leads AS (
    SELECT ref_code FROM referrals WHERE lead_email IS NOT NULL
),
referred AS (
    SELECT ref_code, referred_sub, referred_tenant_id, created_at
    FROM referrals WHERE source = 'signup'
),
activated AS (
    SELECT t.id AS tenant_id, min(n.finalized_at) AS first_finalized_at
    FROM tenants t JOIN notes n ON n.tenant_id = t.id AND n.finalized_at IS NOT NULL
    WHERE t.signup_source = 'referral'
    GROUP BY t.id
)
SELECT
    l.week,
    (SELECT count(*) FROM weeks w WHERE w.week = l.week)                        AS notes_finalized,
    count(DISTINCT l.note_id)                                                   AS notes_with_recipient_link,
    count(*)                                                                    AS links_created,
    count(*) FILTER (WHERE l.delivery_status = 'sent')                          AS links_sent,
    count(l.first_viewed_at)                                                    AS first_viewed,
    count(r.link_id)                                                            AS links_responded,
    count(l.cta_clicked_at)                                                     AS cta_clicked,
    count(ld.ref_code)                                                          AS leads,
    count(rf.referred_sub)                                                      AS signup_requested,
    count(rf.referred_tenant_id)                                                AS verified,
    count(a.tenant_id) FILTER (
        WHERE a.first_finalized_at <= rf.created_at + interval '7 days')        AS activated_7d,
    round(100.0 * count(rf.referred_tenant_id)
          / nullif(count(l.first_viewed_at), 0), 2)                             AS loop_efficiency_pct
FROM links l
LEFT JOIN responded r  ON r.link_id = l.id
LEFT JOIN leads ld     ON ld.ref_code = l.ref_code
LEFT JOIN referred rf  ON rf.ref_code = l.ref_code
LEFT JOIN activated a  ON a.tenant_id = rf.referred_tenant_id
GROUP BY l.week
ORDER BY l.week DESC;
