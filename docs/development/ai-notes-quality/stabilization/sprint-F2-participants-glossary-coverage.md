# Sprint F2 — Correct participants, glossary suggestions and coverage

## Goal

Remove false participant identities and pseudo-corrections; retain important information in readable notes. Dependency: F1 final validation and reproducible diagnostics. Owner: backend + frontend, bilingual QA.

## F2-01 [P0] — Require person and participation evidence

Touch points: meeting_doc/verify.py::verify_introduction, roles_table.py::_introductions, roles_table.py::real_name, compose.py::speakers_of, context/framing prompts.

Current capitalization/source-presence checks and broad introduction patterns such as das ist do not establish that a name denotes a person. Mapping a proposed introduction to the next different voice can also misassign an inserted broadcast clip.

Tasks:

- Separate entity type (person/event/institution/topic/unknown) from participation role (host/guest/interviewee/quoted speaker/unknown).
- Require evidence that the named person is introduced as that participant. Use a structured semantic classification where lexical rules cannot establish this; do not hardcode the specific event name as a blacklist.
- Do not assign the next voice solely because it follows a supposed introduction. Require a supported identity link; otherwise keep an unknown voice/role.
- A quoted speaker is not automatically a guest. An institutional representative can be a participant when explicitly evidenced; the institution itself is not a human guest.
- Keep source speaker IDs and acoustic segmentation unchanged.
- Validate final framing against accepted participant records, rejecting invented participants before display.

Tests: “Midterm-Wahlen” as subject must never become guest; “Das ist das Repräsentantenhaus” is not a person introduction; “Bei uns ist Anna Müller” can introduce a person; English inserted Trump quote remains a quoted speaker; unknown host remains unknown; false person metadata is rejected even when all its words appear in the source.

Acceptance: zero false named guests in sentinels, with legitimate guests retained. Missing identity reduces specificity rather than inventing a participant.

## F2-02 [P1] — Stop presenting grammatical changes as ASR corrections

Touch points: meeting_doc/entities.py, domain/glossary.py, correction APIs and the component actually rendering “Names in this note”. Locate that component before editing; do not assume the transcript correction sheet owns this block.

candidates_in uses capitalization; resolve uses similarity. Article-only changes can pass the 0.8 threshold. German capitalization is not proof of a proper name.

Tasks:

- Distinguish spelling correction from article removal, grammatical inflection, capitalization formatting and entity extraction.
- Suppress article-only/format-only suggestions as “heard → corrected” pairs; do not change the transcript for these cases.
- Typed person/name suggestions require entity evidence. “Behauptung” is not a name. An explicitly saved specialist term or institution may remain valid glossary vocabulary; do not prohibit users from manually saving ordinary terms.
- Add a backend guard against automatic learning of pseudo-corrections, not only frontend filtering. Keep suggestions distinct from persisted glossary entries.
- Render “Added to the glossary” only from a successful persistence response or a verified existing matching entry. Show proposed/failed states separately and provide removal for entries the user can manage.
- Inspect actual write provenance before claiming prior entries were automatically added. Offer targeted cleanup for identified bad entries; do not bulk-delete the user's glossary.

Tests: Das Repräsentantenhaus → Repräsentantenhaus, Die Behauptung → Behauptung produce no ASR correction; a genuine person misspelling can be proposed; manual institution vocabulary remains supported; failed API save never shows “Added”; reload reads persisted state; tenant isolation remains enforced.

## F2-03 [P0] — Diagnose and repair important-proposition loss

Touch points: pipeline.py stage tracing, extraction windows, verification budgets, merge, salience, overview.py and rendering.

Trace the $5,000 promise through each stage before changing prompts. Record extracted/not extracted, rejected/uncertain, merged, selected/not selected, written/suggested, with reasons and original evidence references. Distinguish budget/provider failures from contradicted claims.

For the election fixture preserve the condition of winning both chambers and all-adult-citizen recipient whenever the promise is included. Detailed must include this central proposition. Short mode can omit lesser details, but not remove conditions from claims it includes. A riskier statement must not disappear without a visible completeness signal simply because it consumes verification budget.

Use a bounded targeted recovery pass for important missing propositions; then pass recovered text through F1. If the source remains ambiguous or verification fails, mark incomplete rather than manufacture a precise claim. Improve salience so an isolated register-check sentence does not become the entire overview when central explanatory propositions are available.

Test majority thresholds, election powers, strategic trade-off, conditional payment and source-attributed allegations. Add negative tests where the promise is absent from the input: recovery must not invent it. Check additional-details duplicates and conflicting claims separately.

## Definition of done and rollback

- [ ] No event/topic presented as a person or guest.
- [ ] No article-only pseudo-correction in the names block or automatic glossary writes.
- [ ] Glossary status reflects persistence and existing access rules.
- [ ] $5,000 proposition has an auditable stage outcome and appears accurately in Detailed.
- [ ] Final-output accuracy and coverage meet the shared gates on held-out recordings.
- [ ] Existing ASR, human edits and unrelated glossary entries remain intact.

Roll back new inference rules through versioned deployment/profile state; retain diagnostic and correction history. Any remediation of stored glossary entries is a separate explicit, reversible operation.
