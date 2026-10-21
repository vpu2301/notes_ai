# Prompt and copy review — German and Ukrainian

Created by Sprint N5 (note instructions): no de/uk sign-off checklist existed. Every German or
Ukrainian string a model reads, or a customer sees, is listed here with who signed it off.
A row is **pending** until a native speaker has read it in context and initialled it; the
study report marks results that depend on a pending row.

How to review: read the text as a customer (or, for a prompt string, as an instruction a
careful person would follow). Check meaning, register and that nothing in it could be read as
a fact about a real meeting. Write the date and your initials; note changes as a new row.

## Note instructions (N2–N5)

| Item | Where | Language | Reviewer | Date | Status |
|---|---|---|---|---|---|
| `STYLE_PREAMBLE` / `STYLE_RULE` — the FORM block's frame | `services/note-service/src/note_service/domain/meeting_doc/prompts.py` | de | | | pending |
| `STYLE_PREAMBLE` / `STYLE_RULE` — the FORM block's frame | same | uk | | | pending |
| `WRITING_STYLE_LINES` — formal, informal, academic (N0) | `services/note-service/src/note_service/domain/meeting_doc/prompts.py` | de | | | pending |
| `WRITING_STYLE_LINES` — formal, informal, academic (N0) | same | uk | | | pending |
| Preset "Client-ready (German)" | `services/note-service/tests/fixtures/instructions/client_ready_de.txt` = `web/src/components/noteInstructionsPresets.ts` | de | | | pending |
| Study text `client_ready_de` | `eval/instructions/v1/docs/client_ready_de.txt` | de | | | pending |
| Study text `de_team_kurz` | `eval/instructions/v1/docs/de_team_kurz.txt` | de | | | pending |
| Study text `de_vertrieb` | `eval/instructions/v1/docs/de_vertrieb.txt` | de | | | pending |
| Study text `de_geschaeftsfuehrung` (guidance in German — the mixed-language row) | `eval/instructions/v1/docs/de_geschaeftsfuehrung.txt` | de | | | pending |
| Study text `uk_brief` | `eval/instructions/v1/docs/uk_brief.txt` | uk | | | pending |
| Study text `uk_team` | `eval/instructions/v1/docs/uk_team.txt` | uk | | | pending |
| Study text `uk_formal_long` | `eval/instructions/v1/docs/uk_formal_long.txt` | uk | | | pending |
| Study text `uk_sales` (guidance in Ukrainian — the mixed-language row) | `eval/instructions/v1/docs/uk_sales.txt` | uk | | | pending |
| Red-team texts in de/uk (`lang_de_*`, `lang_uk_*`, `lang_mixed_injection`) | `eval/instructions/v1/hostile.json` | de, uk | | | pending |

The eight study texts were drafted by engineering, not written by native speakers as N5 asks;
they stand in until replaced or signed off. The card, the guide panel and the "Not applied"
sentences are English only (N3 non-scope: the settings pages are not translated).

## Narrated families and the outline step (B2)

| Item | Where | Language | Reviewer | Date | Status |
|---|---|---|---|---|---|
| `EXTRACT_NARRATED` — the extraction addendum for broadcast/memo | `services/note-service/src/note_service/domain/meeting_doc/prompts.py` | de | | | pending |
| `EXTRACT_NARRATED` | same | uk | | | pending |
| `CONTEXT_NARRATED` — subject, thesis, key facts | same | de | | | pending |
| `CONTEXT_NARRATED` | same | uk | | | pending |
| `BLOCK_NARRATED_LEAD` / `BLOCK_NARRATED` — numbers in the point, the verdict kept | same | de | | | pending |
| `BLOCK_NARRATED_LEAD` / `BLOCK_NARRATED` | same | uk | | | pending |
| `SUMMARY_NARRATED` — thesis first, no chronology | same | de | | | pending |
| `SUMMARY_NARRATED` | same | uk | | | pending |
| `OUTLINE_SYSTEM` — the sections of the argument | same | de | | | pending |
| `OUTLINE_SYSTEM` (written from the de text) | same | uk | | | pending |
| `CERTAINTY_PHRASES` / `CERTAINTY_CLAUSES` / `VERDICT_SUFFIX` for reported, unproven, refuted | `services/note-service/src/note_service/domain/meeting_doc/support.py` | de, uk | | | pending |

The de texts follow the sprint order's wording with its examples moved into Quillhaven
vocabulary; the uk texts were written by engineering from the de ones.
