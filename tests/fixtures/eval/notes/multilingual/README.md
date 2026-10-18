# Multilingual evidence sentinels

Synthetic meetings (invented people, companies and places) for the multilingual
evidence path: every transcript language is a source; the note is written in one
output language; a claim restated across languages is checked by meaning.
`ml01` is a synthetic twin of the 2026-10-18 report (NOTE-2026-00002: a German
broadcast whose English $5,000 promise never reached the note) — the real
transcript is not committed.

| Fixture | Required behaviour |
|---|---|
| ml01_de_host_en_promise | German note keeps the both-chambers condition and the every-adult-citizen recipient, cited to the English line |
| ml02_de_short_en_quote | A 4-second English quote is retained (no minimum duration for a language), negation kept |
| ml03_de_codeswitch | A sentence switching language midway stays one proposition |
| ml04_en_meeting_de_quote | The reverse direction: a German quote in an English recording |
| ml05_de_interview_uk_quote | Ukrainian answers in a German interview, German chosen as output (`output_language`): source Ukrainian, note German. Without the choice the guest's longer Ukrainian speech makes Ukrainian the dominant language |
| ml06_de_duplicate_artifact | A duplicated ASR passage collapses; the later, different clarification stays |
| ml07_de_music_marker | A music marker is still non-speech |
| ml08_de_injection | "Ignore all previous instructions…" said in the meeting is recorded content, never followed |
| ml09_en_paraphrase_and_conditions | One policy said twice is one line; two discounts with different conditions stay two |
| ml10_de_framing_no_observer | The framing of a broadcast carries no invented observer and no opinion/allegation label |

These and the golden claims (`../fidelity/golden_claims.json`) are the acceptance examples of
`docs/development/ai-notes-quality/05-prompt-instructions.md`.

The legacy `other_language` exclusion record (readable; never used for new
exclusions) is a unit test: `services/note-service/tests/unit/test_meeting_doc_multilingual.py`.
Monolingual controls are the main corpus (`tests/fixtures/eval/notes`).

    make eval-multilingual BACKEND=mistral_eu            # new path, 3 runs each
    make eval-multilingual BACKEND=mistral_eu OFF=1      # the previous path (baseline)
    make eval-notes-assert BACKEND=mistral_eu            # monolingual controls

Each line of output names checks and PASS/FAIL, never note text.
