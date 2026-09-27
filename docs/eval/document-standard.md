# The document standard — what a generated note must look like

**Status:** Proposed 2026-09-27. **Derived from:** the comparison note on r03 (the shape a reader keeps), corrected by the rules that note breaks (five unsourced claims), and by the product's own contract (every line traceable; nothing invented; the author's words untouched). **Enforced by:** `meeting_doc/doclint.py` (Sprint D1) before a document is written; measured by the eval scorers and the blind rubric in §8.

Numbers below are the standard, not suggestions. Where a value depends on the recording's length, `D` is the duration of transcribed speech in minutes.

## 1. Title

- One line, 30–80 characters, sentence case, in the recording's language; names the subject and, when the recording has one, the angle: *Palantir-Gründung: Peter Thiel, 9/11 und die Anfänge der Datenanalyse* ✔; *Meeting notes — 2026-09-26* ✘; a title that repeats itself or the show's name twice ✘.
- Every proper noun in the title appears in a verified fact. No colon-chains beyond one colon.
- Owned by ADR-0059 (`title_source`); the engine never replaces a person's title.

## 2. Orientation (the first block, no heading)

Two paragraphs of prose, always present, never bullets.

**Paragraph 1 — what this is** (25–60 words): recording type in plain words (*Podcast-Folge*, *Kundengespräch*, *Produktvorstellung*, *Vortrag*, *Teambesprechung*), the show or organisation when introduced or jingled, the subject, the speakers by role and name (*Erzähler/in*; *Gast: Felix Holtermann, Handelsblatt*), and 3–5 themes as a comma list. Every value is verified (type from the classifier + cues; names from introductions with speech share ≥ 15 % or the calendar; themes from the brief). Composed by code when the model's framing fails.

**Paragraph 2 — what is said** (60–140 words, 3–6 sentences): the arc in narrative order — where it starts, what develops, where it ends — with the two or three most specific facts (a number, a date, a name each). Third person, present or past consistently, no "we", no speaker labels, no quotes. Each sentence cites ≥ 1 fact.

A reader who stops after the orientation must be able to say what the recording is, who speaks, and what it covers (blind rubric Q1).

## 3. Sections

- Count: `max(3, min(8, round(D / 4)))` for narrative recordings (podcast, lecture, demo, interview); for meetings the item sections (Decisions, Tasks, Open questions) plus topics under the same rule. A 30-minute podcast has 6–8 sections; a 10-minute clip has 3.
- Order: the order of the recording. A section covers a contiguous span; spans do not interleave. The first section may carry a date when it is about an event (*11. September 2001: Der Auslöser*).
- Size: 2–6 bullets each; a section with 1 bullet merges into its neighbour; a section with > 6 splits by time.
- Item sections (meetings) keep their roles and grammar (`Owner: task — due`); no topic section repeats an item.

## 4. Headings

- A noun phrase, 3–8 words, ≤ 60 characters, sentence case, in the recording's language, naming the **phase or subject** of that span: *Stimmung und Reaktion in den USA*, *Gründung von Palantir*, *Alex Karp: Palantirs ungewöhnlicher CEO* ✔. Generic labels (*Diskussion*, *Einleitung*, *Weitere Punkte*, *Zusammenfassung*), questions, verbs-only, all caps, trailing punctuation ✘.
- Every proper noun in a heading appears in a fact of that section.
- A heading never restates the title; two headings never share > 60 % of their tokens.

## 5. Bullets

- One claim per bullet, 8–25 words, third person, sentence case, no terminal period on fragments, no "and then…" chains. Present tense for narrative and durable facts; past for events with a date.
- **Specific:** every bullet carries at least one of a name, a number with its unit and the speaker's qualifier, a date or time expression, or a term in quotation marks. *90 % Zustimmung für Bush* ✔; *Es gibt viel Zustimmung* ✘.
- **Exact:** numbers, units and qualifiers as spoken (*fast 3.000*, *über 2 Stunden*, *just under 300 gallons*). Never converted, rounded, or made precise (*Viertel vor neun* stays; *8:46 Uhr* is not written unless said).
- **Named:** subjects are names or definite nouns, never pronouns or labels (*Speaker 1*, *Unknown speaker*, *Erzähler*). A reported view names its holder (*laut Holtermann*; *Thiel hält…*), never the narrator.
- **Not a quote:** a bullet is never a transcript sentence or ≥ 80 % of one. Quotes live in sub-bullets (§6) and in the evidence popover.
- **Not description:** scene narration, atmosphere and evaluations (*ein riesiger Feuerball*, *das Boot ist beeindruckend*) are evidence, not bullets.
- **Certainty kept:** forecasts, estimates, proposals, allegations carry their marker (*voraussichtlich*, *Schätzung*, *Vorschlag*) or their chip.
- Hedged, attributed, dated bullets read like: *Aus für Rente mit 63 wird laut Reinbold voraussichtlich abgeschwächt.*

## 6. Sub-bullets

- One level, ≤ 3 per bullet, only for **parts** (components, steps, sides of a design), **examples**, **consequences**, or **one short quote** (≤ 20 words, speaker named, timestamp in the row): *Palantíri: mächtige Steine, mit denen man in die Vergangenheit schauen … kann* under the name's origin ✔.
- A sub-bullet never restates its parent and never introduces a new subject.

## 7. Volume and referencing

- Total words in the body (orientation + sections, excluding tables): `8·D` to `18·D` — a 30-minute recording is 240–540 words; a 60-minute meeting 480–1 080. Below the floor the note is missing content; above the ceiling it is a transcript in disguise.
- Redundancy < 5 % (no fact rendered twice across orientation, sections, tables).
- Every line — sentence, bullet, sub-bullet, table row, presenter line — has a row with quote, timestamp, speaker and cited fact ids; the client shows the words and plays the audio. A line without a row is not written.
- Figures render as a table only for demos, lectures and specification blocks (≥ 3 figures on one subject, ≥ 2 quantity names with units); otherwise inline.
- What was left out is listed, not hidden: *Nicht enthalten: 00:00–00:31 (Werbung), 04:10–04:14 (anderssprachige Passage)*; *Nicht transkribiert: …* with the cause.

## 8. The blind rubric (3 raters, per note, 0–2 each)

| # | Question | 2 | 1 | 0 |
|---|---|---|---|---|
| Q1 Orientation | From the first block alone: what is this, who speaks, what does it cover? | all three | two | fewer |
| Q2 Structure | Do the headings alone tell the story in order? | yes | partly | no |
| Q3 Specificity | Share of bullets with a name/number/date/term | ≥ 90 % | 60–89 % | < 60 % |
| Q4 Faithfulness | Claims not supported by the transcript (rater checks 5 random lines against the words) | 0 | 1 | ≥ 2 |
| Q5 Exactness | Numbers, units, qualifiers as spoken | all | one miss | more |
| Q6 Subjects and roles | Pronouns/labels as subjects; wrong presenter/guest/type | none | one | more |
| Q7 Volume | Within the band for D | yes | ±25 % | worse |
| Q8 Form | Copies, description, redundancy, rendering defects | none | one | more |

Release gate: mean ≥ 13/16 on v2, Q4 = 2 on ≥ 95 % of notes, no note with Q1 = 0. The comparison note on r03 scores Q1 1 (no speakers), Q2 2, Q3 2, Q4 0 (five unsourced claims), Q5 0 ("8:46 Uhr"), Q6 2, Q7 2, Q8 2 → 11/16. Our r03 note 2 scores Q1 1, Q2 0, Q3 0, Q4 1, Q5 1, Q6 0, Q7 0, Q8 0 → 3/16. The standard is met when we score ≥ 13 on the same recording — which requires their structure with our faithfulness.

## 9. What the standard does not require

Prose sections (bullets under headings are the body); slide-like decks; a fixed template shape (structure follows content, ADR-0058 §6); a spec table on every recording; anything the transcript does not contain, however well known.

## In code (2026-09-27)

- **Sprint D1 (ADR-0065).** `meeting_doc/doclint.enforce` runs in the worker between the
  pipeline and the writer, and in the eval harness. It checks every rule of §1–§7 that code can
  check, sends hard findings to D2 once (not merged yet), repairs and falls back
  deterministically, and records what is left (`stats.lint`,
  `mdx_note_generation_lint_total`, alert `NoteGenerationLintUnresolved`).
- **§1 titles.** `note_title.py` asks for 30–80 characters with subject and angle. A suggestion
  that breaks §1 is not applied.
- **§8 rubric.** `scripts/eval/notes_pairs.py rubric-build` / `rubric-score` run the blind
  rubric per note, with the release gate. Q3 and Q7 are also read by code in every eval
  (`rubric_auto_q3`, `rubric_auto_q7`).
- **§7 exclusions.** The clients list excluded passages under "Not included".
