# ADR-0021 — Postgres `simple` FTS config for notes search

- Status: accepted
- Date: 2026-05-13
- Sprint: 08
- Deciders: tech lead, NLP lead, SRE lead, content lead

## Context

The notes search endpoint (`GET /v1/notes/search`) is the most
frequently-used query and the most-demanding performance
budget in the product (p95 ≤ 250 ms with `q`, ≤ 100 ms filter-only,
on 100k notes per pilot tenant).

The content is **bilingual** (Ukrainian + English) with heavy
domain terminology. Three candidates were on the table:

1. **Postgres FTS with `simple` config.** Token = lowercased exact
   match; no stemming.
2. **Postgres FTS with `russian` or a hand-curated Ukrainian config.**
   Stems on Cyrillic root, conflates case endings.
3. **OpenSearch / Elasticsearch sidecar.** Sophisticated analyzers,
   relevance tuning, faceting.

## Decision

Ship **Postgres `simple`** in sprint-08. Carry a fall-back plan to
either a custom UK config or OpenSearch when we see real pilot
queries failing.

Rationale:

- Ukrainian morphology is hard. `russian` config doesn't handle UK
  cases correctly; a hand-curated UK dictionary needs a linguist
  contractor (out of sprint-08 budget).
- `simple` is "find the exact lowercased token". Inflected matches
  (задишку vs задишка) won't match — but for sprint-08 we accept
  this trade-off because pilot users can use truncated stems in
  their queries (we'll document the search-tips screen in sprint-15).
- Avoiding the operational burden of OpenSearch in sprint-08 lets us
  hit other targets (chain integrity, optimistic-lock UX, diff
  caching). A separate cluster is more weight than the demo + early
  pilot phase warrants.

## Triggers for revisiting

Move to a heavier solution **only** when one of the following holds:

| signal                                       | next step                                    |
| -------------------------------------------- | -------------------------------------------- |
| Any tenant > 1M notes                        | Partition + re-eval FTS plan                 |
| Search p95 > 500 ms for 5+ consecutive days  | Profile; consider OpenSearch                 |
| Content lead documents > 10 pilot examples of poor result quality | Begin UK FTS dictionary work |

The dashboard panel `Search latency split by has_q` in the
`sprint-08-reports` Grafana board is the canonical place to watch the
first two signals.

## Consequences

Positive:
- Zero new ops surface.
- Snapshot consistency: search hits exactly what's in `note_versions`.
- ts_headline gives us a free snippet on the same query.

Negative / accepted:
- Cyrillic queries that rely on stemming will miss inflected matches.
- No relevance tuning beyond `ts_rank` (which we don't currently use
  — results are ordered by date `DESC, id DESC` for stable
  cursor pagination).
- Synonym handling (e.g., abbreviation vs expansion) is not in scope.
  Sprint-15 adds a `query_expansion` layer (ADR-0038).

## Links

- Sprint-08 spec §4.7.
- `services/note-service/src/note_service/domain/search.py`.
- ADR-0038 — search query expansion over the same `simple` config.

---

## Amendment (2026-07-22, sprint 13) — reference tables reuse `simple`; withdrawn detail

> **Historical note.** This amendment originally documented the МКХ-10
> (ICD-10) reference table, which was removed together with the medical
> vertical. The generic precedents it set still stand: global reference
> tables (e.g. `voice_commands`) reuse the same `simple` FTS
> configuration for the same no-trusted-Ukrainian-stemmer reason, keep
> their ranking statement in exactly one shared place, and are
> RLS-exempt (allowlisted in `scripts/ci/check-rls-policies.py`)
> because they are published global data with no tenant dimension.
