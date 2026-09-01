# Autocomplete architecture (sprint-10)

The highest-frequency typing touchpoint. p95 ≤ 80 ms is the load-bearing
constraint that shapes every choice here.

## Topology

```
   FE keystroke ──► POST /autocomplete/suggest ──► autocomplete-service
                                                          │
                                       trie cache (Redis) │
                                                          ▼
                                              candidates (top-20)
                                                          │
                                              full ranker (Bayesian + recency
                                              + length + diversity)
                                                          ▼
                                                  top-N suggestions
                                                          │
                              ◄──── 80ms p95 (cache hit) ──┘

   FE accept/reject ──► POST /autocomplete/telemetry ──► PII scrubber ──► buffer
                                                                          │
                                                                          ▼
                                                  autocomplete_telemetry (partitioned)
                                                          │
                                            nightly roll-up @ 03:30 UTC
                                                          ▼
                          autocomplete_phrases (impression_count, acceptance_count)
                                                          │
                                            redis INCR version_tag
                                                          ▼
                                              next suggest rebuilds trie
```

## Three-scope visibility model

| source  | tenant_id | owner_user_id | visible to        | writable by                  |
| ------- | --------- | ------------- | ----------------- | ---------------------------- |
| system  | NULL      | NULL          | everyone          | `tenant_writer` (seed only)  |
| tenant  | set       | NULL          | tenant            | admin / tenant_admin         |
| user    | set       | set           | own tenant (cache); ranked only for the owning user | the owning user |

RLS PERMISSIVE `tenant_visibility` enforces visibility; RLS
RESTRICTIVE `write_user_phrases` enforces write rules.

## Caching (ADR-0025)

Per-(tenant, language, user) trie. Lazy invalidation via
`version_tag`. Per-key Redis lock prevents thundering herd. Versioned
serialisation so format upgrades are non-breaking.

## Ranking

```
score = source_priority * Beta(1,9)-acceptance * recency_boost * length_score
```

- Source priority: user 1.0, tenant 0.6, system 0.3.
- Bayesian prior Beta(1,9): zero-impression phrases start at 0.1.
- Recency boost: +20% for today's accepts, decays exp(-days/7) over 30
  days.
- Length score: shorter completes faster (~50-char midpoint).

Diversity guard: rapidfuzz Levenshtein on candidate suffixes; drop
near-duplicates within Levenshtein 3.

## Telemetry pipeline

1. FE posts `request_id`, `event`, `prefix`, `phrase_id`/`snippet_id`,
   `context`.
2. PII scrubber: email / phone / card-like / ID-like patterns redacted.
3. In-memory batch buffer; flushes every 5 s OR 100 rows.
4. Insert into `autocomplete_telemetry` (monthly partition).
5. Nightly roll-up aggregates yesterday's events into the phrase
   counters; bumps `version_tag`; trie cache rebuilds lazily.

## PII scrubber

Conservative regex (generic PII set):
- Email (RFC-5322-lite).
- Card-like digit sequences (13–19 digits, space/dash grouped).
- National-ID-like patterns (letters + long digit run).
- Phone numbers (international `+` or separator-broken groups).
- Long contiguous digit runs (catch-all).

Production code path: telemetry intake redacts prefix + context;
phrase-write endpoint rejects 422 if the prefix contains a match.

The pattern set is documented in `docs/security/autocomplete-pii-scrubber.md`;
regex updates require security review.

## Data model

| table                          | partition  | purpose                                     |
| ------------------------------ | ---------- | ------------------------------------------- |
| `autocomplete_phrases`         | none       | three-scope corpus (RLS PERMISSIVE+RESTRICTIVE) |
| `autocomplete_snippets`        | none       | trigger → expansion (same RLS)              |
| `autocomplete_telemetry`       | monthly    | high-volume events; no RLS (ADR-0025)       |
| `autocomplete_rollup_progress` | none       | idempotency marker for the nightly job      |

## Audit

8 sprint-10 kinds (`autocomplete.phrase.created/updated/deleted`,
`autocomplete.snippet.{same}`, `autocomplete.phrase.write_rejected_pii`,
`autocomplete.rollup.completed`).

## Hand-offs

- **Other surfaces** — consume the same `/suggest` endpoint; context
  field hints (`field`, `preceding_text`) tunable per surface.
- **Layer C** — generative completion lives beyond this
  service.
- **Sprint-17** — admin UI consumes existing CRUD endpoints.
