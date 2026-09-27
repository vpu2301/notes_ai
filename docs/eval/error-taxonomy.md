# Error taxonomy for transcripts and notes

**Purpose:** every defect seen in a note or transcript gets a category code, a detector (automated where possible) and a prevention rule in code. New defects are filed under a code; a defect that fits no code gets a new one here. Evidence base: the ZEIT "Was jetzt?" audit (r01, 2026-09-22), the Pardo 65 GT walkthrough (r02, 2026-09-25), the Simplicissimus Palantir episode (r03, 2026-09-26, three of our outputs and the comparison note).

Severity: **S1** the reader is misled (false content); **S2** the reader cannot use the note (missing or unreadable); **S3** the note is worse than it should be (form).

## A. Transcript layer

| Code | Category | Definition | Seen in | Detector | Prevention |
|---|---|---|---|---|---|
| T-INJ | Injected text | Words in the transcript nobody said in this recording (prompt echo, cross-note names). S1. | r02 "Gysi, Moderator II, moderatorin, narrator, speaker background"; r03 "Gysi" ×3 | I2 echo diagnostics; `must_not_contain`; two-tenant suite | I2: vocabulary filter, stored hint, word-level echo guard |
| T-COV | Lost speech | Speech present in the audio, absent from the transcript. S2. | r02 first 45 s (presenter's name and dealer) | F1 coverage (`transcribed_ms / speech_ms`), gap causes | F1: capture timing, VAD pad/floor, decode-twice |
| T-LANG | Wrong-language handling | Speech in a second language translated, garbled or silently dropped. S1 when translated. | r02 Ukrainian → English fragments; comparison product → Russian gibberish; r03 English clip → "Technological / Facts, den" | per-segment `language`; `other_language` exclusions listed | I2 T4 per-chunk language ID, never `translate` |
| T-ENT | Misheard names and terms | A name or term transcribed as another word. S1 when it changes meaning. | r01 "Schmerz", "Schlesing", "Uschmanow"; r03 "Heiland hier" (Palantir), "Tilda/Tiers" (Thiel), "heiligianisch" (hegelianisch), "Carp/Karp" | entity scorer vs gold surface forms; within-recording inconsistency count | Q4 tiers (glossary, candidates, bounded model), amendment §2.8 consistency, I2 hint hygiene; corrections → glossary |
| T-DIAR | Speaker fragmentation | Single words assigned to other labels; the author's voice merged with the source. S3, S2 when it breaks attribution. | r03 "Speaker 2: Kann", "Unknown speaker: unter"; r02 one speaker for author + video | micro-turn count; DER on gold | amendment §2.7 merge; I3 T4 Me/Them on web |
| T-DISP | Display fidelity | Fillers, inconsistent punctuation/casing between chunks, raw fallback. S3. | r02 "uh … this is this is", lower-case run-ons | `enrichment` diagnostic; filler count | I3 T2/T3 |
| T-ADV | Non-content passages transcribed as content | Adverts, trailers, jingles, music inside the transcript with no marking. S3, S1 when they feed the note. | r03 film trailer at 00:00; "Unfassbar. Simplizissimus Podcast" | `advertisement` exclusions; cue-word scan | amendment §2.2 exclusion before windowing |

## B. Fact layer (what the engine believes was said)

| Code | Category | Definition | Seen in | Detector | Prevention |
|---|---|---|---|---|---|
| F-INV | Invented claim | A name, number, event or relation not supported by any verified fact. S1. | r01 "Der Start im November bleibt das Ziel"; comparison note r03 "8:46 Uhr", "Nordturm", "Südturm", "World Trade Center", "Hegel", "Gymnastikhanteln" | `invented_claims`, `unsupported_rate`, example echo | Q1 example guard; Q2 support gate; F3 figure verification |
| F-DIST | Distorted claim | Right words, wrong relation or certainty. S1. | r01 "Kein Umsturz zu erwarten ist die Entscheidung", "Kritik an Wahlkreisen" | judge column; hedge scorer; `paraphrase_unsupported` flag | Q2 T4 text-vs-quote; Q4 hedge; certainty kept |
| F-NUM | Missing or wrong number, date, time | A figure the speaker gave is absent, rounded, converted or unit-less; a relative date resolved wrongly. S1 when wrong, S2 when missing. | r01 none of ~3 000, 6 months, 1 Oct, Wed 0:00; r03 "über 2" without "Stunden", "Zwanzig Jahre" as a name; r01 "am Montag" → wrong week | `figure_recall`, `figure_value_accuracy`, `qualifier_preservation`, `date_resolution` | F3 figure validity (amendment §2.3); Q3 T6 dates; Q4 salience |
| F-SUBJ | Unresolved or wrong subject | A statement whose subject is a pronoun, a speaker label, or the wrong person. S1. | r03 "Speaker 1 ist genervt, dass er … Schuhe ausziehen muss" (it is Thiel); "Er ist genervt" | pronoun-initial or label-initial line count | D2 T3: subject must be a name or a definite noun; labels never appear in prose |
| F-ATTR | Wrong or missing attribution | An opinion/forecast without its holder, or with the narrator instead of the person reported. S1. | r01 correspondent's forecast as fact; r03 narrator's report of Thiel's view attributed to "Speaker 1" | `attribution_rate`; narrator-as-actor count | Q4 T4 + D2 T3 narrator rule |
| F-ROLE | Wrong role | Presenter, guest, host, interviewee assigned to the wrong person or to a clip. S1. | r03 "Präsentiert von: Chris Hansen" (trailer); "Gast: Alex Karp" (a subject heard in clips; the guest is Felix Holtermann) | guest/presenter assertions in gold | amendment §2.1 gating by speech share and turns; D2 T4 role table |
| F-TYPE | Wrong recording type | Meeting/lecture/podcast/demo misclassified, changing sections and labels. S2. | r01 "Teambesprechung"; r03 "Vortrag" for a podcast episode | `recording_type_acc` | Q3 classifier + D2 T4 cues (show jingle, guest interview, clips → podcast) |
| F-COPY | Quote as fact | A bullet that is a transcript sentence. S2. | r02 all eight bullets; r03 summary "Er ist genervt, dass er plötzlich seine Schuhe…" | `copied_lines` | F2 T1/T2 |
| F-DESC | Description instead of information | Scene narration, evaluative remarks, empty lines. S2. | r02 "This boat is incredible"; r03 "Ein riesiger Feuerball entsteht", "Alex Karp hatte einen ungewöhnlichen Lebenslauf" | `no_information_lines`, `descriptive`, specificity 0 | F2 T3; amendment §2.5, §5.2 |
| F-DROP | Real content excluded as noise | Speech dropped by the model's noise flag or exclusions. S2. | r01 85 % of facts, whole second story | `excluded_speech`, coverage ratio | Q2 T2 noise policy in code, cap |
| F-COV | Facts missing (recall) | Substance present in the transcript, absent from the note. S2. | r03 Palantir founding, 9/11 report finding, TIA, Karp biography, Habermas; r01 sanctions story | `key_fact_recall`, coverage by third | Q2 budget; Q4 salience; D2 volume budget |

## C. Document layer (how the note is composed)

| Code | Category | Definition | Seen in | Detector | Prevention |
|---|---|---|---|---|---|
| D-ORIENT | No orientation | The top of the note does not say what this is, who speaks, what it covers. S2. | r03 note 1 (bullets only); r03 note 2 ("Vortrag. Es sprechen Erzähler/in und als Gast Alex Karp…" — right form, wrong values) | overview rubric (standard §2) | amendment §2.9; D1 lint |
| D-STRUCT | No or wrong structure | No headings; flat list; sections not in narrative order; one-bullet sections. S2. | r03 note 1; r01 five one-bullet sections | sections count vs duration; bullets per section; order | amendment §5.1 two-stage reduce, §2.6 chapters; D1 lint |
| D-HEAD | Bad headings | Generic ("Diskussion"), all-caps, too long, not naming the phase or subject. S3. | r01 "5 all-caps headings" | heading rules (standard §4) | D2 T2 phase headings; D1 lint |
| D-SPEC | Unspecific bullets | Bullets without a name, number, date or term. S2. | r03 note 1 all eight | specificity per bullet | amendment §5.2; D1 lint |
| D-VOL | Wrong volume | Too little for the duration (8 bullets for 30 min) or too much (transcript-length). S2/S3. | r03 note 1; r02 | words per minute of audio | D2 T1 volume budget |
| D-RED | Redundancy | Same fact in lead, key points and topics. S3. | r01 four points ×3 | `redundancy` | Q3 T4 |
| D-NEST | Missing sub-structure | Parts, examples or quotes flattened into one long bullet or scattered. S3. | r02 swim platform; r03 TIA criticism | nested-bullet share where gold has parts | F2 T4 children |
| D-REF | Missing reference | A line without a source; a quote without speaker and time. S2 (trust). | comparison note: none per line | `lines_cited` | Q5 rows and popover |
| D-LABEL | Labels in prose | "Speaker 1", "Unknown speaker", "Erzähler/in" as actors in sentences; wrong label ("Vortrag"). S2. | r03 note 2 | label-token scan | D2 T3; D1 lint |
| D-LANG | Wrong language or register | Note not in the recording's language; first person; "we"; chat tone. S3. | r01 "heute" → date grammar; r02 first person | `first_person_lines`; language check | F2 T3; Q3 T6 |
| D-FORM | Rendering defects | Glyphs in text, tables where none belong, speaker-avatar false positives. S3. | r01 "HTHinweis"; r02 ❝; r03 "Technische Daten" | render lint; snapshot tests | Q3 T5; F2 T5; amendment §2.4 |

## D. Isolation and process

| Code | Category | Definition | Seen in | Detector | Prevention |
|---|---|---|---|---|---|
| P-ISO | Cross-workspace or cross-user content | Any content from another tenant or user. S0 (incident). | not seen (r02 was within-workspace) | I1 two-tenant suite | I1; RLS gates |
| P-MEAS | Unmeasured change | A prompt or rule shipped without a gold-set number. S2 (process). | eval harness fed zero turns until Q1 | nightly gates; PR check | Q1; Q6 required checks |
| P-PROMPT | Content-bearing prompt | Example text that can be echoed as a fact. S1. | r01 November sentence | `EXAMPLE_PHRASES` test | Q1 T4 |

## Using the taxonomy

Every regression assertion, scorer and PR label references a code. The weekly quality report (Q6 T8) counts dismissals and corrections by code (the corrections route's `reason` enum maps onto codes: `not_said` → F-INV/T-INJ, `wrong_owner` → F-ATTR/F-SUBJ, `not_a_decision` → F-DIST, …). A category whose count rises two weeks running opens a sprint item under the owning sprint above.

## Where the codes live (2026-09-27)

- **One table in code.** `scripts/eval/taxonomy.py` holds every code with its layer and
  highest severity. It also holds which codes each checklist check, scorer metric and dismiss
  reason stands for. A metric, check family or reason without a code fails
  `tests/unit/test_notes_gates.py`.
- **Checklists.** `notes_assert.py` prints each check's codes beside PASS or FAIL. A checklist
  may pin codes per check under `"codes"`; r03 does, since its forbidden strings are
  injections, a trailer, a wrong table and invented claims.
- **Scorers.** `notes_eval.py` reports carry the metric-to-code table. Detectors added with
  this document: `label_lines` (D-LABEL), `unresolved_subject_rate` (F-SUBJ),
  `unspecific_bullet_rate` (D-SPEC), `words_per_minute` (D-VOL) and `headings_per_10_min`
  (D-STRUCT).
- **Dismiss reasons.** The weekly report counts dismissals by code as metric `dismiss_code`:

  | Reason | Code |
  |---|---|
  | `not_said` | F-INV (T-INJ cannot be told apart from a dismissal) |
  | `not_a_decision`, `not_a_task` | F-DIST |
  | `wrong_owner` | F-ATTR |
  | `wrong_date` | F-NUM |
  | `duplicate` | D-RED |
  | `not_relevant` | F-DESC |

  The job's headline flags a code whose dismiss share rose two weeks running.
- **PR labels.** The pull-request template asks for the codes a change addresses.

Not built here: the D1 lint and the D2 sprint items (T1 volume budget, T2 phase headings in
full, T3 subject and narrator rule, T4 role table). Their work orders are not in the repo.
