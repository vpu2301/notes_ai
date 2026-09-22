# ADR-0058 — The meeting document engine: extract, verify, compose

**Status:** Accepted · **Date:** 2026-09-20

## Context

The Notes tab was empty after every meeting. A transcript landed in one
section and that was the product: everything downstream — the recipient
page, action items, the client version, carry-over — worked on text a
person still had to write.

The obvious approach, one prompt over the whole transcript, fails in a
specific way: a small model loses the middle of a long meeting, invents
an owner for "we should", turns a proposal nobody answered into a
decision, and shifts a number by a digit. Every one of those is the kind
of mistake that makes a reader stop trusting the whole document, and no
amount of prompting reliably removes them.

## Decision

**The model proposes typed claims; code decides which are true.**

    windows → extract (one call each) → verify → merge
            → reduce (two calls) → render → write

1. **Windows, not one pass.** The transcript is cut at turn boundaries
   into ≤ 6 000-character windows with one turn of overlap, so a decision
   stated at the end of one window meets its agreement at the start of
   the next. A turn longer than the cap is split at sentence ends and
   keeps its original number. Every millisecond is covered exactly once,
   which is what makes coverage-by-third measurable.
2. **Verification is the load-bearing step** (`verify.py`, pure):
   - the **quote** must, normalised, be a substring of the turn it cites
     or of the window. No match → the fact is dropped. Nothing reaches a
     note without words that were actually spoken;
   - the **owner** must be a speaker, a name candidate or a capitalised
     token in the window. A first-person commitment takes the quote's own
     speaker; "we should" takes nobody; an owner we cannot place is
     cleared, never guessed;
   - the **date** must occur in the turn. Unparsed but spoken text is
     kept as text; a date nobody said is never written;
   - every **number** in the text must occur in the quote or turn, else
     it is removed and the fact flagged;
   - a **decision** with no agreement — an explicit formula, or another
     speaker agreeing within ±3 turns — is downgraded to a key point.
3. **Reduce never sees the transcript.** It receives verified facts only,
   and every sentence and bullet must cite fact ids; one that cites
   nothing, or carries a number not in its cited facts, is dropped.
4. **Render is code.** Actions come out as `Owner: task — due`, which is
   exactly what `parse_action_lines` reads back — so a generated task
   appears on the recipient's page, in the carried-over block and in the
   corrections routes with no second parser. A section with no verified
   facts is left **empty**; filler is indistinguishable from a result.
5. **The writer never overwrites a person** (`writer.py`). Per section:
   empty, or byte-identical to what the last generation wrote (compared
   against `stats.section_hashes`) → ours to write. Anything else is the
   author's; its facts are stored `suggested` instead. A run that changes
   nothing writes no version, so a re-delivered job after a crash is a
   no-op rather than a second entry in History.
6. **A queued job in a separate process.** `libs/jobs` (leases,
   heartbeats, `waiting_on_model`, the usage ledger) gets its first
   consumer; `python -m note_service.worker` is the same image and the
   same code, in its own container. Rejected: Redis Streams (no
   `waiting_on_model`, no ledger) and the in-process scheduler (built for
   daily chores, shares the API's event loop).
7. **A snapshot, not a live read.** note-service has no service identity,
   so it reads `/asr/jobs/{id}/result` once, in the user's own request,
   with the user's own bearer — and keeps what it read. A re-labelling in
   asr-service afterwards cannot silently change what a finished note was
   built from. The object is written **before** the transaction: an
   orphan object is swept in a day, an orphan row never runs and never
   explains itself.
8. **Section roles.** `TemplateSection.role` (additive; v1 templates fall
   back to an id map) is what the engine, the shared page, the
   action-item projection and the PDF all decide by. One vocabulary, in
   `meeting_doc/roles.py`.

## On prompt injection

A transcript is untrusted input and anyone can say anything into a
microphone. The mitigations are data delimiters, schema-constrained
output, no tools, and a rendering step that is code. The **guarantee** is
narrower and worth stating precisely: a claim with no real quote is
dropped, and a claim with no second-speaker agreement cannot become a
decision. If someone genuinely says "the price is zero", that is a thing
that happened in the meeting and it is recorded as a key point with the
words attached — hiding it would be its own kind of lying.

## Consequences

- Two AI versions per meeting (items, then the document), both labelled
  `metadata.source = "generation"`. Accepted: tasks appear in seconds
  rather than after the summary.
- A deployment with no chat backend, or no object store, simply never
  starts a generation; the note is what it was before. `from-transcript`
  catches every failure — the engine may never cost a user their note.
- Quotes and item text are content: cascade-deleted with the note, in the
  DSAR export, and never in a log, an audit payload or a job row
  (payloads carry ids only).

## Not built in this pass

The gold set (`eval/notes/v1`) is real meeting transcripts and personal
data; it cannot be created from here. The compose/Helm wiring for
`note-worker`, the dashboards and most client surfaces are listed in
`open-sprint-work.md`. The harness (`scripts/eval/notes_eval.py`,
`make eval-notes`) and the single-pass baseline were built in Sprint 37 —
see the amendment below.

---

# Amendment — Sprint 37: tiers, budgets, fairness and retention

**Status:** Accepted · **Date:** 2026-09-20

Four decisions, all of them about the engine being a thing a business
runs rather than a thing that works.

## 1. A workspace is only routed to a processor it has acknowledged

`workspace_model_settings` (migration 0053) holds a workspace's provider,
tier, budget and the processors its admin has agreed to **by name and
region**. The list an admin is shown is computed from the same `Registry`
object that routes the calls (`processor_routes()`), never from copy
text. So adding a backend to `config/models.yaml` cannot put a new
company in somebody's data path: `effective()` drops that workspace to
`platform/standard` until an admin agrees, and the Data page says why.

A processor that moved region is a NEW processor. The region is most of
what a customer is agreeing to.

The alternative — a disclosure page maintained by hand — was rejected
outright. A page that can be wrong is worse than no page, because people
believe it.

## 2. Budgets are checked at enqueue, and say so

`check_allowed()` runs before the snapshot and before the job: a
workspace over `monthly_budget_cents` (or its plan's
`ai_cents_per_month`, default $20) queues nothing. The note still works —
recording, transcript, the author's own typing — and the client says
`budget_exceeded` instead of showing a spinner that never resolves. The
admins hear once per calendar month, guarded by a Redis key: losing the
guard costs a duplicate banner, which is the cheap failure.

`generation_enabled = false` is the same path with a different sentence.
Both are the workspace's own choice, so neither is an error anywhere.

## 3. Fairness lives in the claim, not in the handler

The sprint asked for a per-tenant in-flight cap in the handler. A cap in
the handler does not solve the problem it was aimed at: with one worker
and a FIFO queue, a workspace that uploads fifty recordings still puts
fifty jobs *in front of* everyone else's single meeting, and the cap only
decides how fast its own fifty run.

So `jobs_claim_fair` (migration 0055) ranks each workspace's queued jobs
and orders by rank **before** `run_at`: the first round takes one job
from every waiting workspace. The in-flight cap rides along in the same
statement, as headroom rather than a threshold, because a claim of two
against a cap of three must not take a workspace from two to four.

Priority still wins over fairness: `regenerate` is 5, a follow-up 3, an
automatic run 0. Somebody pressing Regenerate is watching the screen.

The cap is soft — two workers claiming in the same instant can each see
the other's rows only after they commit. Making it exact means
serialising every claim on a per-tenant lock, which costs more than the
thing it prevents.

## 4. A transcript snapshot dies with the run that needed it

The snapshot exists because note-service has no service identity and
cannot re-read asr-service's artifact later. That is a reason to keep it
for minutes, not a reason to hold a second copy of every meeting. The
worker deletes it at the end of every run, success or failure, and a
daily sweep deletes anything older than a day whose worker was killed
first. `model_usage` gets the 400-day retention its own migration
promised in 0023 and never enforced; terminal `jobs` rows go after 30
days. Both run as `tenant_writer`, because `app_role` cannot delete from
either — by policy, on purpose.

## Shadow runs

`MDX_NOTE_GENERATION_SHADOW_BACKEND` runs a candidate on 5 % of
generations, sampled deterministically on the generation id so a sample
is 5 % of *meetings* rather than of attempts. Its output is counted and
dropped: no version, no item, no second snapshot. A workspace is shadowed
only onto a processor it has already acknowledged — a rehearsal is still
processing somebody's meeting.

## What the bake-off will record here

The candidates are registered in `config/models.yaml` with
`enabled_in_envs: [dev, test]` so the harness can reach them and no
customer workspace can. When one is selected, this section gets: the
model and its pin, the processor (name, region, DPA), the price, the
structured-output mode that worked, and the three-run numbers behind the
choice. The premium candidate is registered nameless and disabled,
because a processor entry is a disclosure and the Data page reads these
names.

## 5. Generate Summary — the engine on request, and a section the note did not have

**Amended 2026-09-21.**

The note opened at Record is written automatically when the recording
lands (§2 of the first amendment). Two things were still missing for
someone reading the Notes tab: a way to ask for the write-up when it
did not happen — the note predates the engine, the workspace had it
off, the model was down — and somewhere for the summary to go, because
the default meeting template had no section with the `summary` role and
`render.emit` dropped it on the floor.

*Generate Summary* is `POST /v1/notes/{id}/generation` as it already
was — reason `regenerate`, priority 5, ten a day — behind a button that
appears in exactly one place: the Notes tab of a draft the reader may
edit, made from a recording, with no generation row. Once a run exists
the status line takes over, as before. There is no summary-only scope:
the summary is reduced from the extracted facts, so the expensive part
of the run happens either way, and a second job kind would be a second
thing to keep honest.

The meeting templates (`meeting_notes`, all three languages) gain an
*Overview* section, `summary` role, right under *My notes*. That is the
one seam the writer's rule in §5 of the decision had to give: a section
the template has but the note's content does not was *offered, not
added*, on the grounds that adding one changes the document's shape
under the author. It does not — every client draws the template's
sections whether or not the content carries them, so the section is
already on the page, empty. The writer now adds it, after the sections
the note had, and only when the rendering is not empty. The rest of the
rule stands: text the author typed is never replaced.

The summary prompt says, in all three languages, to write in the third
person as a report of what happened — never *we*, *I* or *our* — and to
say what was discussed, decided and next, with no filler.
`PROMPT_VERSION` is `2026-10-2`.

### Amended later the same day: a record, not a retelling

The first notes the engine wrote for an interview-style recording read
like a retelling — "man glaubte, dass…" — with fact ids in the prose and
a Decisions list of verbatim asides. The prompts now ask for one neutral
business statement per fact, third person or impersonal, never "X
said/thinks", never "we", with the ids in `fact_ids` only; the renderer
strips any id a model still writes into a bullet or a sentence and keeps
it as a citation. Verification no longer reads "ja", "okay", "passt" or
"добре" as consent — in a lively meeting they open half the turns — and
files a decision whose text is its quote copied as a key point. The
evidence contract is unchanged: every fact still carries a verbatim
quote, and the note text is what the reader sees while the quote lives in
`note_generated_items`. `PROMPT_VERSION` is `2026-10-3`.

### Amended 2026-09-21 (later): understand the conversation before writing

Prompt `2026-10-4` adds one model call between merge and reduce: a
**context pass** that reads the verified facts as a whole and returns the
conversation type, the subject, the themes, one framing sentence and the
ids of the facts a reader must know first. Topics and summary are then
written against that brief (and run in parallel), the Overview opens with
the framing sentence, and the topics section opens with a *Key points*
block. The evidence contract holds: the pass never sees the transcript,
may only name ids it was given, and its framing sentence is number-checked
against the facts like a summary sentence — a framing the facts cannot
support is not written.

Two more rules from the same review. **Certainty is meaning**: each fact
carries a `certainty` the prompts must keep in the text, and the renderer
strips only the flat passive openers ("It was noted that") — never a
hedge ("It was estimated that"). **Noise is named, not narrated**: the
extractor flags turns that are not the conversation from a closed
vocabulary; facts quoted from them are dropped, and the Overview ends
with a one-line transcript note rendered in code from that vocabulary.

## 6. Structure follows content

**Amended 2026-09-22.** The document was template-shaped: every client
drew every template section, heading and all, and the engine filled the
slots it had roles for — a roster into *Attendees*, `###`-headed topics
into *Discussion*, and nothing where the template had no slot. That put
empty headings on a note that said "Call Peter tomorrow", a
*Participants* list of "Speaker 1 / Speaker 2" on every recording, and a
generic *Discussion* over every topic.

Now the content decides. `NoteSection` gains an optional `title`; a
section without one has the canonical bytes it always had (the field is
absent, not null), so no version hash moves. The engine writes an
unheaded opening block, `gen:overview`, and one `gen:<slug>` section per
topic the conversation had, titled from the content — none when the
conversation has one subject or too little material. Item kinds keep
their semantic homes (the template's, or a headed section of their own),
and only when there is something to put there. Nobody is listed as an
attendee automatically. On a re-run, what the engine wrote last time and
does not write again is removed or emptied unless a person edited it —
the ownership rule of §5, applied to absence as well as presence.

The clients render what the content has, in its order, and head a block
only when it has a name. Three kinds of empty block still show while a
note is editable, because nothing else gives the author a way in: the
pad, a typed field, and — on the older form-shaped templates that have
no pad — the template's own fields. `section_labels`, the PDF, the shared
page, the client document and the exports follow the same rule. Older
notes render as they are: a template section with text keeps the
template's name; without text it is simply not drawn.

Not done, on purpose: `NoteContent` still names a template, the item
projection still reads `action_items` / `next_steps` by key, and the
carry-over block still lands in `action_items`. Those are homes, not
headings, and a template stays the way a family declares its fields.
