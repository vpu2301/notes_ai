# ADR-0024 — Canonical JSON via RFC 8785 (JCS)

- Status: accepted
- Date: 2026-05-14
- Sprint: 09
- Deciders: tech lead, security lead, legal counsel

## Context

The bytes that get hashed (audit chain, note-version chain) must be
deterministic across:

- Python runtimes (3.12, future 3.13).
- Service replicas (different machines, different glibc).
- Storage round-trips (JSONB → asyncpg.Record → Pydantic → dict).
- Re-canonicalisation by an independent verifier (legal counsel may
  commission an external auditor).

Three options:

1. **Plain `json.dumps(obj, sort_keys=True)`**. Works *almost*. Edge
   cases: number formatting (`1.0` vs `1`), Unicode escapes, NaN/Inf
   handling, key collision behaviour all differ across implementations.
2. **JCS (RFC 8785)**. A spec, with a vetted implementation
   (`rfc8785` PyPI). Already used by sprint-02's audit hash chain.
3. **Roll our own**. Strictly more risk; no benefit.

## Decision

Use **RFC 8785 (JSON Canonicalization Scheme)** via the `rfc8785`
library. Centralise in `audit.canonical.canonicalize`. One
implementation for every hash-chain consumer.

Any change to a canonical input shape requires a new ADR + a version
bump + a forward-only migration (previously-hashed records keep their
original version forever).

> **Historical note.** This ADR originally also served the sprint-09
> e-signature flow (`medical_kep.canonicalize_report`), which was
> removed with the medical vertical. The canonicalisation decision
> stands unchanged for the audit chain and note-version hashing.

## Consequences

Positive:
- Byte-stable across implementations.
- The audit chain and the note-version chain share the same primitive,
  so a verifier who validates one gets the other's canonicalisation
  "for free".
- The `rfc8785` library is small, vetted, and pure-Python — easy to
  embed in any future external verifier we ship.

Negative / accepted:
- Adding a field to a canonical shape is not free — we have to bump
  the canonical version and accept that records hashed under prior
  versions remain verifiable against the old shape indefinitely.
- We can't sneak in non-JSON-natural types. UUIDs → strings, datetimes
  → ISO-8601 strings, bytes → base64 strings; the canonicaliser raises
  on anything else.

## Links

- `audit.canonical` (RFC 8785 implementation).
- ADR-0008 (audit hash chain), ADR-0020 (note-version chain).
- Sprint-09 spec §2.3, §2.4.
