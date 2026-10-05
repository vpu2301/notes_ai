# Meeting notes — decision log and GA checklist

The written document: what shipped, what it is measured on, and what has
to be true before it stops being a beta. One entry per pilot week, plus
the GA entry that answers *"would we build the same thing today?"*.

Metrics come from `scripts/eval/notes_eval.py` (gold set) and, for
production behaviour, from the note-generation dashboard rows. Neither
this page nor anything feeding it carries a quote, a name or a line of
anyone's note.

## GA checklist

Binary. A line without evidence is not met, and "looks fine" is not
evidence. Status as of **2026-09-20** (Sprint 37 built; nothing measured
on a deployment yet).

| # | Gate | Status | Evidence |
|---|---|---|---|
| 1 | Concept §7 GA gates met on the test split with the standard-tier model, per language, report ≤ 7 days old | **not met** | harness and the committed synthetic corpus exist (`make eval-notes`, `tests/fixtures/eval/notes/`); the real gold set `eval/notes/v1` does not, and no candidate has been run |
| 2 | Production, 28 days, ≥ 150 generated notes opened: kept-line ≥ 70 %, dismiss ≤ 10 %, regenerate ≤ 20 %, zero overwritten author texts | **not met** | no production generations yet |
| 3 | Blind benchmark run and reported; any "better than" wording matches the result | **not met** | protocol in Sprint 37 B-4; arms A/B/C need no competitor access, so it does not wait on counsel |
| 4 | Tier decision recorded in ADR-0058; routing flipped through shadow; rollback tested | **partly** | shadow flag, `tier-flip` runbook and the rollback path are built (ADR-0058 amendment); no tier selected |
| 5 | `/settings/data` live; every processor in routing appears on it; premium cannot be enabled without acknowledgement (test in CI) | **met (code)** | `web/src/pages/settings/DataSettingsPage.tsx`, `tests/dataSettings.test.tsx`, `services/note-service/tests/unit/test_ai_settings.py` |
| 6 | Budgets enforced; weekly cost per meeting-hour per tier | **partly** | enforcement at enqueue + notification are built and tested; the weekly cost report is not |
| 7 | Load scenarios pass on the environment serving the pilot; capacity line written | **not met** | two queue drills pass locally (`tests/load/note_generation/runner.py`); five need staging — `docs/testing/load/notes-README.md` |
| 8 | Failure drills pass (kill at each step; backend down; autosave storm) | **not met** | same |
| 9 | Lifecycle: erase a note → no sidecar row, no snapshot, no follow-up; DSAR export contains glossary and follow-ups | **partly** | snapshots are deleted at run end and swept daily (tested); the erase/DSAR end-to-end test is not written |
| 10 | Alerts with rule tests: failure rate, p95, `waiting_on_model` age, budget, snapshot sweep, writer conflicts | **met** | `infra/prometheus/rules/note-generation.yml` + `tests/note-generation-test.yml`, `model-backends.yml` for the backend half |
| 11 | Tenant-isolation negatives for every route added in 33–37; RLS probes cover every new table | **partly** | `make check-rls` green on 55 tables; the per-route negatives for the Sprint 37 routes are in `test_ai_settings.py`, the RLS probe test is still broken by migration 0028's FK (pre-existing) |
| 12 | No transcript, quote, item text, glossary term or name in logs or audit (CI vocabulary test) | **met** | `make check-notification-pii-free`, the audit-kind documentation test, and the payload assertions in `test_ai_settings.py` |
| 13 | Runbooks: `notes.md`, `model-backends.md`, DSAR; decision log per pilot week and the GA entry | **partly** | `notes.md` (budgets, sweeps, writer conflicts) and `model-backends.md#tier-flip` written; no pilot weeks yet |
| 14 | Counsel's written position on benchmarking filed; no competitor account created or used outside it | **not met** | not asked yet; arms A/B/C do not need it |

**If 1 or 2 fails there is no GA.** The document ships as beta with its
status visible, and the failing metric is named here with the next action.

## 2026-09-20 — Sprint 37 built: tiers, budgets, fairness, retention

What changed, and why each one is the way it is, is in the ADR-0058
amendment. The three things worth repeating here, because they are
product decisions rather than technical ones:

1. **The processor list is computed, not written.** Whatever we say on
   the Data page comes from the routing table itself. We cannot
   accidentally tell a customer the wrong thing about who sees their
   meetings, and we cannot quietly add a company to their data path.
2. **Running out of budget is a sentence, not a spinner.** A workspace
   over its budget keeps recording, keeps its transcripts, keeps its own
   typing, and is told plainly that the write-up is off for the month.
3. **Fairness is in the queue.** Fifty uploads from one workspace no
   longer sit in front of somebody else's single meeting.

Not settled, and it is the whole of gate 1: **no model has been
measured**. The bake-off candidates are registered as eval-only backends
and the harness runs, but the corpus it needs is real meetings under the
consent register, and none exist yet. Until that runs, the tier a
workspace chooses is a choice between two routes to the same model.
