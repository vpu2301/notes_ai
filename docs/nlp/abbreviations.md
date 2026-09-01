# Abbreviation Policy

Pipeline Stage 5 applies a per-tenant + global merged dictionary to
the post-processed text.

## Schema

```
abbreviation_dictionary(
    id, tenant_id NULL=global, language,
    expanded, abbreviated,
    direction (expand | compact | either),
    domain (free-form category, e.g. 'sales' / 'legal' / 'all' / NULL),
    case_sensitive
)
```

Tenant rows override global on the same `(language, expanded, abbreviated)`.

## Direction

- `compact` — REPLACE expanded form with abbreviated. Default.
- `expand` — REPLACE abbreviated with expanded.
- `either` — pass through (the speaker's surface form wins).

## Snapshot semantics

The processor fetches the merged dictionary ONCE per request at
`POST /nlp/process` entry. Admin edits made during an in-flight
request DO NOT affect that request — the snapshot is immutable for
the request's duration.

The snapshot's `fingerprint` (a stable hash) is part of the
idempotence cache key. An admin edit invalidates cached results for
that tenant on the next request.

## Word-boundary matching

Substitutions respect Unicode word boundaries. `ІМ` will NOT match
inside `імпорт` (no boundary on the left). Case sensitivity is per-row.

## Domain filtering

If `ProcessingContext.category` is set (the note template's business
category, sent as `category` on `/nlp/process`), rules with
`domain=category` win over `domain='all'`, which wins over
`domain=NULL`.

This is what lets the same abbreviation expand differently in, say, a
legal-review session than in a sales call — a tenant can scope a rule
to the template categories where it is unambiguous.

## Admin API

- `GET /nlp/abbreviations[?language=]` — paginated list of merged rules.
  Role: any authenticated.
- `PUT /nlp/abbreviations` — upsert one tenant rule. Body:
  `{language, expanded, abbreviated, direction, domain?, case_sensitive?}`.
  Role: `tenant_admin`. Emits `abbreviation.policy.set` audit.
- `DELETE /nlp/abbreviations/{id}` — remove one tenant rule (global
  rules are immutable). Role: `tenant_admin`. Emits
  `abbreviation.policy.deleted` audit.

## RLS

Reads see own-tenant rows OR global rows. Writes are limited to
own-tenant rows. Cross-tenant access is impossible at the DB layer
(RLS-first invariant).

## Global rows

No global dictionary is seeded out of the box — `tenant_id IS NULL`
rows are reserved for operator-managed defaults (loaded via the
`tenant_writer` role). Tenants build their own vocabulary via
`PUT /nlp/abbreviations` and can override any global row.
