# Architecture Decision Records

ADRs capture decisions whose reversal would be expensive — choices about
runtimes, build surfaces, security primitives, and contracts other code
depends on. Casual decisions (file layout inside a service, choice of HTTP
status code for a niche error) do not need ADRs.

Numbering is monotonic and global. Sprint 02 starts at ADR-0006; sprint
03 starts at ADR-0009. Gaps in the sequence (0022–0023, 0026–0028,
0032–0033, 0043–0044) are ADRs that belonged exclusively to the removed
medical vertical; the numbers are retired, not reused.

| #     | Title                                                                            | Status   |
| ----- | -------------------------------------------------------------------------------- | -------- |
| 0001  | Python version pin and `uv` workspace           | Accepted |
| 0002  | Distroless, nonroot production containers| Accepted |
| 0003  | Typed `Secret[T]` wrapper                        | Accepted |
| 0004  | Single-helper tenant connection (`tenant_connection`) | Accepted |
| 0005  | Observability stack (logs / traces / metrics)     | Accepted |
| 0006  | Keycloak as Identity Provider                         | Accepted |
| 0007  | RLS-first tenant isolation                 | Accepted |
| 0008  | Hash-chained audit log + `audit_writer` escape hatch | Accepted |
| 0009  | Inference engine: faster-whisper      | Accepted |
| 0010  | Queue tech: Redis Streams (jobs) + Kafka later | Accepted |
| 0011  | 3-layer encryption envelope           | Accepted |
| 0012  | WebSocket vs WebRTC for streaming dictation | Accepted |
| 0013  | Whisper streaming windowing (4s + 2s overlap) | Accepted |
| 0014  | Punctuation model selection               | Accepted |
| 0015  | Rule-based number normalization       | Accepted |
| 0016  | JSONB template schema + cosmetic-vs-structural rule | Accepted |
| 0017  | HF Space embedded demo stack                  | Deprecated — demo stack removed |
| 0018  | Demo privacy contract (tmpfs-only)              | Deprecated — demo stack removed |
| 0019  | WER standing release gate                   | Deprecated — eval harness removed |
| 0020  | Append-only note versioning                    | Accepted |
| 0021  | Postgres `simple` FTS for notes                   | Accepted |
| 0022  | PAdES-LTV canonical PDF                                                          | Withdrawn — medical vertical removed |
| 0023  | Signing provider abstraction                                                     | Withdrawn — medical vertical removed |
| 0024  | Canonical JSON via JCS                         | Accepted |
| 0025  | Autocomplete trie + Redis cache               | Accepted |
| 0026  | Server-side file-key signing via UAPKI                                           | Withdrawn — medical vertical removed |
| 0027  | Patient identity & crypto-shredding strategy                                     | Withdrawn — medical vertical removed |
| 0028  | Privacy-ops deployment                                                           | Withdrawn — medical vertical removed |
| 0029  | Redis Streams as the notification event bus | Accepted |
| 0030  | Redis pub/sub for cross-worker WebSocket fan-out | Accepted |
| 0031  | Notification email carries pointers, never content | Accepted |
| 0032  | Typed anamnesis field extraction stage                                           | Withdrawn — medical vertical removed |
| 0033  | Admin/content separation via break-glass                                         | Withdrawn — medical vertical removed |
| 0034  | Speaker-diarization backend — Silero VAD + ECAPA + online clustering | Accepted |
| 0035  | Conversation capacity — single mixed worker pool with weighted caps | Accepted |
| 0036  | Layer C inline completion — local Gemma behind a provider seam | Accepted |
| 0037  | Audio replay — clip-on-demand over the GCM envelope, token-streamed | Accepted |
| 0038  | Search query expansion — synonym dictionary over `simple` FTS | Accepted |
| 0039  | MFA/TOTP — auth-service proxy enforcement, envelope-encrypted secret in Keycloak attributes | Accepted |
| 0040  | Session revocation — auth-service-pushed Redis denylist, fail-open checks | Accepted |
| 0041  | Scheduled jobs — shared in-process runner per service, CLI twin for cron | Accepted |
| 0042  | HTTP/2 POST streaming fallback — closed with data, not built | Accepted |
| 0043  | Clinical corpus governance                                                       | Withdrawn — medical vertical removed |
| 0044  | LLM-assisted corpus review                                                       | Withdrawn — medical vertical removed |
| 0045  | Batch diarization: N-speaker agglomerative clustering, word-level attribution, speaker naming | Accepted |
| 0046  | Model hosting is configuration — `libs/models` and the backend registry | Accepted |
| 0047  | A bounded dual-issuer period — `MDX_IDP_MODE=dual` (= ADR-IDX-09) | Accepted |
| 0048  | Self-serve signup stays on the BE-0 path; referral attribution is a stamp on `referrals` | Accepted |
| 0049  | Recipient links are mailed inline by note-service; opt-out is a global hashed suppression | Accepted |
| 0050  | Workspace sharing policy lives on the tenant; the product line is the price of the free tier | Accepted |
| 0051  | A note is a living document: the finalize lifecycle is retired | Accepted |
| 0052  | Diarizer v2 — engine behind a seam, hosted on a GPU endpoint | Accepted |
| 0053  | Dual-channel capture on macOS (microphone + call audio) | Proposed |
| 0054  | The legacy batch clusterer is kept (removal precondition not met) | Accepted |
| 0055  | The meeting note is created at record start, not after transcription (amended Sprint 35: linkage by `item_key`, corrections, glossary) | Accepted |
| 0057  | One client document, and meetings that remember the last one | Accepted |
| 0058  | The meeting document engine: extract, verify, compose (amended Sprint 37: workspace model settings, acknowledged processors, budgets, fair claim, snapshot retention) | Accepted |

## Template

```markdown
# ADR-NNNN — Title

**Date:** YYYY-MM-DD
**Status:** Proposed | Accepted | Deprecated | Superseded by ADR-NNNN
**Deciders:** <names / roles>

---

## Context

What changed in the world that forces a choice now? What constraints?

## Decision

What we are doing. Be unambiguous.

## Consequences

Positive and negative effects. Be honest about the cost.

## Alternatives considered

What we rejected and why.

## Trigger conditions for revisiting

What signal would make us re-open this decision?
```

## Authoring rules

- Number monotonically. Don't reuse a number even after deprecation; mark
  the original as `Superseded by ADR-XXXX` and link forward.
- Keep ADRs short. Two pages is the upper bound. If you need more, the
  decision is several decisions; split.
- Reference the ADR from the affected code (`libs/secret/README.md` →
  ADR-0003). Discoverability matters more than completeness.
