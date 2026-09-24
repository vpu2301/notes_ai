# Summary Engine v2 — Diagnosis, Targets, Plan

**Status:** Proposed · **Owner:** Product + CTO · **Date:** 2026-09-22
**Repo baseline:** `vpu2301/notes_ai` @ `summaries` (`fbba745`, 2026-09-22)
**Input:** the side-by-side audit "Summary Engine v2: Beating Granola" (ZEIT "Was jetzt?" update, 22.09.2026; 24 reference facts; our note 3/24, one invented sentence, five distortions; the comparison note 20/24, zero invented).
**Sprints:** Q1–Q5 (`sprint-Q*.md` in this folder).

---

## 1. What the audit found, and what the code says caused it

The audit's conclusion — *"a pipeline problem, not a prose problem"* — holds. Every symptom has a mechanism in the checkout, and none of them is "the model writes badly". Labels follow PO OS §45.

| # | Symptom in the note | Mechanism in the code | Evidence | Sprint |
|---|---|---|---|---|
| 1 | ~85 % of the facts missing; the second story absent; fragments at 01:03, 01:20, 04:45, 05:59 "nicht berücksichtigt" | The extractor returns a `noise` list of turn numbers (`schema.NoiseTurn`), and `verify.verify_facts` drops **every fact whose turn is in it** (`verify.py` L375–380). The flag is the model's opinion and is trusted without a check. A long turn is split into pieces that **share the original turn number** (`windows.split_long_turn` L158–201, "pieces keep the ORIGINAL turn's number"), so a flag on one piece of a 4 000-character monologue silences the whole monologue. A podcast is three long turns, so one flag removes a story. | **Proven** (code) | Q2 |
| 1b | Even unflagged windows are thin | `MAX_FACTS_PER_WINDOW = 12` for a 6 000-character window (`schema.py` L45, `windows.py` L36). Dense speech (news, lectures) carries 20–30 atomic facts per window. | **Strong signal** | Q2 |
| 2 | "Der Start im November bleibt das Ziel" — appears nowhere in the source | It is the example in the German summary prompt: `REDUCE_SUMMARY_SYSTEM["de"]` L299–300 *„Der Start im November bleibt das Ziel“, nicht …*. The extraction shots (L185–208) also carry "November launch", and `EXTRACT_SYSTEM` carries "Sanktionen gegen Russland bleiben durch Lücken in der Durchsetzung begrenzt" (L127–128) — one topic away from the recording. `_summary` keeps a sentence when it cites any known fact id and its **numbers** are supported (`pipeline.py` L423–435); a sentence with no number and a valid id passes. | **Proven** (code) | Q1 |
| 2b | Could it be another workspace's recording? | No path: reduce prompts receive only `facts_block` of this run (`prompts.facts_block`); the worker reads the snapshot by `generation.snapshot_key` with `aad=generation_id.bytes` (`generate_note.py` L113–115); the snapshot is discarded after the run (L242). | **Proven** (code) | Q1 (test only) |
| 3 | Five distortions ("Kein Umsturz zu erwarten ist die Entscheidung", "Kritik an Wahlkreisen", …) | Two of them are the reduce step paraphrasing verified facts into new claims: the only check on a summary sentence is number support. The others are extraction `text` drifting from its `quote`: `verify` checks the quote is real, the numbers, the owner and the date — never whether `text` still means what the quote says. | **Proven** (code) | Q2 |
| 4 | "Teambesprechung", "Meeting notes", "ist die Entscheidung" | The family (which fact kinds are offered) is chosen **by template code only**: `jobs/generate_note.py` L98–99 → `types.family_for_template`. The context pass does return `conversation_type` (`ContextOut`), but it is stored in `stats` and never used (`pipeline.py` L198–204). `REDUCE_CONTEXT_SYSTEM["de"]` offers "Teambesprechung" as a type example (L342), and no rule stops a small model from picking it for anything with two speakers. The template pill on the web shows the template's name (`NoteEditorPage.tsx` L1817–1822); with language `auto` the template is the **English** `meeting_notes` (`notes_from_transcript.py` L315). | **Proven** (code) | Q3 |
| 5 | Same four points in the lead, the key points and the topic headings | `render.render_sections` writes the framing sentence, the summary sentences, the key-point bullets **and** the topic bullets from the same fact list with no cross-view dedupe (L396–424). A topic with one bullet is emitted as a section (L382–394). | **Proven** (code) | Q3 |
| 6 | "HTHinweis zum Transkript" | The transcript note is a prose paragraph appended to the overview (`render.transcript_note` L131–143, appended L413–415). The web treats any paragraph opening with `≤ 4 words + ": "` as a speaker turn (`web/src/lib/richText.ts` L59 `SPEAKER`, L140–153) and draws initials (`RichText.tsx` L86–99, `speakers.ts` L14–19): **H**inweis … **T**ranskript. English shows "TN". | **Proven** (code) | Q3 |
| 7 | "heute" → "22.09.2026"; "am Montag … gewesen" → 28.09.2026; quotes still say "am Montag" | nlp-service `DateNormStage` (`stages/date_norm.py` L281–312; weekday rule L453–461 always forward) runs on every read of a meeting result (`asr-service/routers/jobs.py` L836–841) with no `stages_disabled` and no `reference_date` (anchor = `date.today()` of the nlp server, `process.py` L295). Sprint G0 (2026-09-20) specified the fix; it is **not on `summaries`**. `parse_due` (`action_items.py` L232) is also forward-only. | **Proven** (code) | Q3 |
| 8 | Names unusable ("Schmerz", "Schlesing", "Uschmanow"); no attribution | `glossary.canonical_owner`, `terms_in`, `prompt_block` exist and are called by nothing ("blocked on the engine"). `pipeline.run(name_candidates=…)` exists; `handle_generate` never passes it (`generate_note.py` L125–134). `Fact.certainty` is parsed and then **dropped** — `VerifiedFact` has no such field, so nothing downstream can label a forecast. No `attributed_to` field exists. | **Proven** (code) | Q4, Q5 |
| 9 | The eval could not have caught any of this | `notes_eval.py::as_asr_result` L169–183 emits `turns[].text`; `windows.turns_from_result` L106–107 reads `turns[].paragraphs`. Confirmed by running it: 0 turns. The pipeline arm has only ever evaluated an empty transcript. | **Proven** (run) | Q1 |

Two ASR errors the audit lists ("streichen"/"schützen", "viel Unmut, ja") are transcription, not summarisation. They are out of scope here and go to the speaker-labeling / ASR quality backlog.

## 2. What is right and stays

- The architecture (windows → typed facts with verbatim quotes → code verification → compose from verified facts only) is the reason the note had **only one** invented sentence and it came from the prompt, not from the recording. Single-pass systems invent from the recording. Keep it (ADR-0058).
- `verify.py` already does the four hard checks (quote real, owner present, date spoken, numbers said) and the decision/proposal downgrade. Q2 adds the fifth (meaning preserved) and applies the same discipline to the reduce step.
- The job/worker/idempotency/RLS plumbing (`libs/jobs`, migration 0052, `note_generations`) is sound. No sprint here touches it beyond adding columns.
- `note_generated_items` already holds quote + timestamps + speaker per item line. Q5 extends it to every line.

## 3. Outcome, targets, gates

**Outcome we are buying:** a reader who was not there can trust every line of the note, see where it came from, and find every fact that mattered — for a meeting *or* for a recording that is not a meeting.

Metrics are the audit's, measured by the harness Q1 repairs, on gold set `eval/notes/v2` (§5). "Baseline" is our single-pass arm (`--arm single_pass`), not a competitor's product (§6).

| Metric | Definition (Q1 implements) | Now (audit sample) | Q2 gate | Q4 gate | Q5 gate |
|---|---|---|---|---|---|
| Unsupported lines | written lines whose content the cited facts do not support (deterministic support check; human audit on 20 docs) | ~50 % | ≤ 2 % · 0 invented | ≤ 1 % | ≤ 1 % |
| Invented claims | lines with a name, number or event not in any verified fact | 1 | 0 | 0 | 0 |
| Example-phrase echo | output lines containing any `EXAMPLE_PHRASES` entry | 1 | 0 | 0 | 0 |
| Key-fact recall | reference atomic facts present (content-word overlap ≥ 0.6) | 13 % | ≥ 60 % | ≥ 85 % | ≥ 90 % |
| Coverage ratio | worst third ÷ best third of key-fact recall | n/a | ≥ 0.7 | ≥ 0.85 | ≥ 0.9 |
| Excluded speech | seconds of speech dropped as noise ÷ total speech | large | ≤ 2 % | ≤ 2 % | ≤ 2 % |
| Recording-type accuracy | on the labelled set | wrong | — | ≥ 95 % | ≥ 95 % |
| Redundancy | lines whose content repeats another line (Jaccard ≥ 0.6) | 4 × 3 | — | < 5 % | < 5 % |
| Entity accuracy | gold entities named correctly, when the name is in glossary/calendar/candidates | 1 of 5 | — | ≥ 90 % | ≥ 97 % |
| Hedge preservation | gold hedged statements still hedged in the line | 3 of 4 | — | 100 % | 100 % |
| Attribution | opinion/forecast/proposal lines that name an actor | 0 | — | 100 % | 100 % |
| Date resolution | unit set: "am Montag … gewesen" → 21.09.2026; "bis Mittwoch 0 Uhr" → 23.09.2026 00:00; "heute" unchanged in text | wrong | — | 100 % (Q3) | 100 % |
| Blind pairwise vs single-pass baseline (3 raters, ≥ 85 pairs) | preference | — | — | ≥ 50 % | ≥ 65 % |
| Latency guardrail | p50 end-of-recording → note, 60-min meeting, staging | baseline | ≤ +30 % | ≤ +30 % | ≤ +30 % |

Guardrails that must not move: notes CRUD and autosave latency; no content in logs/stats/reports; cost per meeting-hour reported weekly (Sprint 37 ledger).

## 4. Architecture delta

```
asr-service  GET /asr/jobs/{id}/result
   └─ Q3: conversation results skip date_norm/number_norm/…; reference_date = job date (Sprint G0)

note-worker  jobs/generate_note.handle_generate → meeting_doc.pipeline.run
   windows      Q2: pieces get their own line number; facts and noise cite lines
   classify     Q3: NEW — recording type from the first windows + calendar + user's meeting_type → Family
   extract      Q2: fact budget ∝ window density; Q4: attributed_to; certainty kept
   verify       Q2: noise policy in code (duration, entities, language, duplicate); text-vs-quote support check
                Q3: tense-aware date resolution; Q4: entity resolution against glossary/calendar/candidates
   merge        unchanged
   context      Q3: subject → note title when the title is the default
   reduce       Q2: support gate on every summary/topic/framing line; regenerate once; else code-only overview
   render       Q3: one fact rendered once; no single-bullet topics; exclusions are data, not prose
                Q4: attribution suffix; Q5: key-dates block; per-line citations
   sidecar      Q2: stats.excluded_ranges; Q3: note_generations.recording_type (0057)
                Q5: note_generated_items.cites/certainty/attributed_to; summary & topic lines become items

web            Q3: "Not included" panel from excluded_ranges; recording-type label instead of template pill
               Q5: evidence popover on every line (quote, timestamp, audio), certainty chip, corrections panel

eval           Q1: harness reads what the engine reads; scorers for every metric above; regression cases;
                   nightly job; single-pass arm as the baseline column
```

No new service, queue, table beyond one column-add migration in Q3 and one in Q5, no Redis, no new model operation. The one new model call (Q3 classification) is small and runs once per generation.

## 5. Gold set `eval/notes/v2`

Extends `tests/fixtures/eval/notes/README.md` (v1). Lives in the eval bucket, as `eval/notes/v1` does; the repo holds the five synthetic v1 files plus new synthetic ones and the assertion files.

- **Mix (target 100):** 40 internal meetings, 15 client calls, 15 podcasts/broadcasts, 10 interviews, 10 lectures/webinars, 10 one-to-ones or voice memos. 50 % German, 40 % English, 10 % Ukrainian. Include noisy audio and heavy ASR name errors.
- **Per recording, annotators write:** atomic key facts; actions (text, owner, due); decisions; open questions; `recording_type`; `entities` (canonical + the surface forms ASR produced); `hedged` statements with their modality; `dates` (text + resolved value against the recording date); `speakers` (label → name); `topics` (title + start time); `must_not_contain` strings.
- **Regression case #1** is the ZEIT episode. The transcript is third-party content: it goes in the bucket and `scripts/eval/local/` (gitignored), never in the repo. The repo carries `r01.assertions.json` (the checklist strings from the audit). A synthetic in-repo twin `m06_de_news_podcast.json` (invented names, same shape: host, correspondent, sound bite, two stories, hedges, mangled names, relative dates) runs in CI.
- **Scoring:** automated first (Q1), blind human pairwise second (Q4, Q5). Reports are numbers and ids only.

## 6. Legal constraint on the comparison

The meeting-document concept (§2.4, 2026-09-20) already records that Granola's Platform Terms §3.4 prohibit using the service for benchmarking a competing product. The audit's open question ("do we have the right to collect Granola outputs?") is therefore answered for now: **no**, unless counsel says otherwise. Raters compare our engine against (a) the single-pass baseline arm on the same model and (b) human-written reference summaries. Existing outputs that consenting pilot users already have from their own tools may be shown to raters only with that user's consent and are never stored in the eval set.

## 7. Sprint plan

| Sprint | Weeks | Customer-visible outcome | Exit criterion |
|---|---|---|---|
| **Q1** Measure first | 1 | (internal) Every metric in §3 has a number for our engine and the baseline; the November sentence is impossible; nightly eval runs. | Harness feeds the engine real turns; scorers pass their unit tests; baseline report in `docs/eval/`; `EXAMPLE_PHRASES` test green. |
| **Q2** Nothing dropped, nothing invented | 2 | Both stories in the note. No line without support. Excluded speech named and ≤ 2 %. | Q2 gates in §3. |
| **Q3** The document fits the recording | 2 | Recording type detected and shown; no Decisions on a broadcast; one fact once; no HT; dates right and the transcript verbatim; a real title. | Recording-type ≥ 95 %; redundancy < 5 %; date unit set 100 %; no rendering regressions (snapshot tests). |
| **Q4** Names, attribution, coverage | 2 | Known names spelled right; every opinion carries its holder; long recordings keep numbers, dates, actors; topics have sane boundaries. | Entity ≥ 90 %; attribution 100 %; recall ≥ 85 %; blind pairwise ≥ 50 % vs baseline. |
| **Q5** Traceable lines and claim labels | 2 | Click any line → quote + audio; forecast/opinion chips; key-dates block with .ics; short/standard/detailed; corrections feed the glossary. | Pairwise ≥ 65 %; 100 % of lines carry a working citation; hedge 100 %. |

Team: 1 backend, 1 web, 1 floating (gold set, eval, infra). Native clients follow in Sprint 33C/35's plan once Q5's data model is stable; nothing in Q1–Q5 breaks the macOS/iOS clients (all client-facing changes are additive fields).

## 8. Kill criteria and NOT NOW

**Stop and reassess if:**
- After Q2, on the stack model, unsupported lines stay > 5 % with the deterministic gate → the model is the bottleneck; pull the Sprint 37 bake-off forward before Q3.
- After Q4, recording-type accuracy < 85 % → replace the model classifier with user selection only (meeting type picker) and drop automatic detection.
- After Q5, blind preference vs the baseline < 55 % → the pipeline's prose ceiling is the problem; stop adding sections and run the tier change.

**NOT NOW:**
- Positions map (P2-4). No evidence users ask for it; needs disagreement detection we cannot verify.
- External entity enrichment (P2-8). Sends recording content to a third party; egress allowlist forbids it; no consent model exists.
- A production LLM judge. Eval instrument first (decision 2 in the README).
- Wikidata / web lookup for names. Same egress reason; glossary + calendar + bounded model correction first.
- Sound-bite (quoted clip) detection as a diarization feature. Q4 does the cheap heuristic only.
- Fine-tuning on corrections. They feed glossary, eval and prompts.
- Changing the note's template at generation time. The template is a home for sections, not a heading; only the label changes (Q3).
- Live in-meeting summaries; auto-sending anything; a second LLM client library.

## 9. Debt and risks carried

| # | Item | Severity |
|---|---|---|
| D-1 | No service-to-service identity: generation starts only from a client request (unchanged). | P1 before beta |
| D-2 | `Fact.certainty` parsed and discarded until Q2. | fixed Q2 |
| D-3 | Evidence UI on web (Sprint 35) is not built: `getGeneratedItems` is exported but no component calls it. Q5 builds the per-line version. | P1 |
| D-4 | Language `auto` picks the English template (`TEMPLATE_LANGUAGE_FALLBACK`). Q3 fixes the label; the template choice itself is left. | P2 |
| R-1 | The stack model (Gemma 3 4B) may not reach the Q2 gates. Kill criterion 1. | — |
| R-2 | Prompt injection via speech: schema output, quote verification, support gate. Q2 adds the injection fixture to the regression set. | — |
| R-3 | Third-party transcript in the eval bucket (ZEIT). Internal use, not redistributed, gitignored. Counsel to confirm. | Counsel |
