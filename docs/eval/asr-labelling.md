# ASR gold set — labelling rules (`eval/asr/v1`)

**Sprint TQ1 T2.** How a reference transcript and its spans are written.
The harness (`scripts/eval/asr_eval.py`) scores against these files. A
reference written to other rules measures the labeller, not the engine.

Content never enters git. Labellers work on files fetched from
`s3://notes-eval/asr/v1/<id>/` into `eval/asr/v1/<id>/` and upload them back.
See `eval/asr/v1/README.md` for fetching, adding and erasing a recording.

## 1. Process

1. **Draft.** `make eval-asr BACKEND=inproc_cpu_asr IDS=<id> DRAFT=1`
   writes the in-process backend's segments, in the reference format, to
   `scripts/eval/local/asr-draft/<id>.reference.json`. That backend runs
   large-v3, the strongest model we run.
2. **Correct from the audio.** Listen to every segment. The draft is a
   typing aid. It is never evidence, so a labeller who accepts a draft line
   without hearing it has not labelled it. The budget is about 4× real time
   per pass.
3. **Second pass (test split).** A different person listens again and
   corrects. Set `reference_passes: 2` in the manifest row. Dev-split files
   need one pass.
4. **Spans.** Mark entities, numbers and dates, non-speech regions and
   code-switch regions in `spans.json` (§4).
5. **RTTM.** Write speaker turns from Audacity labels with
   `scripts/eval/labels_to_rttm.py`.
6. **Check.** `make eval-asr-validate` must show 0 problems for the row.

## 2. Verbatim-lite

The transcript holds what was said, as a careful listener would write it
down.

| Rule | Detail |
|---|---|
| Content words exactly as spoken | Grammar errors, dialect forms and wrong words the speaker said stay. We do not correct the speaker. |
| Hesitations dropped | de "äh, ähm, öh, hm"; en "uh, um, erm, hmm"; uk "е, ем, мм, гм". The scorer drops them on both sides as well. |
| False starts | A broken-off word is dropped ("Wir ha- wir haben" → "wir haben"). A repeated whole word is kept once only if it was said twice as a word ("das das" is kept). |
| Discourse words are words | "also", "ja", "genau", "okay", "so", "well", "like", "ну", "от", "так" are kept. They are speech, not hesitation. |
| Numbers | Write them as a reader would. Use digits for amounts, dates, times and years, as in "22. Juni", "350 Euro", "3,5 %" and "2026". The scorer maps number words to digits on both sides, so either form scores the same. |
| Names | Use the canonical spelling. Put the person's or company's own spelling in `spans.json`, and mark it `accept` with its inflected forms. |
| Punctuation and case | Write normal sentence punctuation and case. The scorer ignores both for WER. TR-09 reads punctuation from the engine, not from the reference. |
| Unintelligible | `[?]` for a word nobody can make out. Keep the rest of the line. The scorer drops `[?]`, so neither side is judged on a word no human could hear. Use it sparingly. |
| Overlap | Each speaker gets their own segment with their own times. Segments may overlap in time. |
| Language | Every segment carries the language it is spoken in (`de`, `uk` or `en`). A German sentence that quotes an English phrase is split at the switch (§4, code-switch). |
| Non-speech | Music, jingles, silence, adverts and noise get **no** reference text. They are marked as regions in `spans.json`. An ad read is speech: transcribe it, and also mark the region `ad`. |

## 3. Files

`reference.json` is a list of segments, in time order:

```json
[
  {"start_ms": 12400, "end_ms": 17850, "speaker": "S1", "text": "Guten Morgen, wir beginnen mit dem Projektstatus.", "language": "de"}
]
```

`speaker` is a stable per-recording label (S1, S2 …), never a name.
Segments follow sentences or turns and are no longer than about 30 s.

`spans.json`:

```json
{
  "entities":    [{"start_ms": 41000, "end_ms": 41900, "text": "Handala", "type": "other", "accept": ["Handalas"]}],
  "numbers":     [{"start_ms": 52000, "end_ms": 53100, "text": "22. Juni", "kind": "date"}],
  "non_speech":  [{"start_ms": 0, "end_ms": 14000, "kind": "jingle"}],
  "code_switch": [{"start_ms": 88000, "end_ms": 97500, "language": "en"}]
}
```

The formats are enforced by the pydantic models in `scripts/eval/asr_gold.py`.

## 4. Spans

- **entities**: every mention of a person, company, product or place,
  with the time it is said. `text` is the canonical spelling, and mentions
  with the same `text` are one entity for TR-05. `accept` lists inflected
  forms that count as right (Welcherings, Handalas, "Петра" for "Петро").
- **numbers**: amounts, counts, percentages, dates and times, with `kind`
  set to `number` or `date`.
- **non_speech**: every stretch of 2 s or more of music, jingle, silence,
  advert or noise, with `kind` set to `music`, `jingle`, `silence`, `ad` or
  `noise`. The hallucination metric (TR-02) counts `music`, `jingle`,
  `silence` and `noise`. TR-07 counts every region of 5 s or more. Set
  `non_speech_seconds` in the manifest row to the total.
- **code_switch**: every stretch spoken in a language other than the
  recording's, with that language. The segments inside it carry that
  language too.

## 5. Worked examples

"Heard" is what the speaker said. "Reference" is what we write.

### German

| # | Heard | Reference | Rule |
|---|---|---|---|
| 1 | "Äh, also, wir haben, ähm, das Budget überzogen." | "Also, wir haben das Budget überzogen." | hesitations out, discourse word kept |
| 2 | "Wir ha- wir haben das gestern besprochen." | "Wir haben das gestern besprochen." | false start dropped |
| 3 | "Das das ist wichtig." (said twice) | "Das das ist wichtig." | repeated whole word kept |
| 4 | "Der Liefertermin ist der zweiundzwanzigste Juni." | "Der Liefertermin ist der 22. Juni." | digits for dates; span `numbers` kind `date` |
| 5 | "Wir liegen bei drei Komma fünf Prozent." | "Wir liegen bei 3,5 %." | digits for amounts |
| 6 | "Wegen dem Wetter kommt er später." | "Wegen dem Wetter kommt er später." | the speaker's grammar stays |
| 7 | "Peter Welchering hat das recherchiert." | "Peter Welchering hat das recherchiert." | entity span, canonical spelling |
| 8 | "Der Sprecher sagt: *we will respond with force*." | "Der Sprecher sagt:" (de) + "We will respond with force." (en) | split at the switch; `code_switch` region |
| 9 | 14 s of intro music, then "Hallo und willkommen." | no text for the music; "Hallo und willkommen." | `non_speech` kind `jingle` |
| 10 | "Dieser Podcast wird unterstützt von …" (ad read) | the ad read as spoken | speech: transcribe it; `non_speech` kind `ad` |

### English

| # | Heard | Reference | Rule |
|---|---|---|---|
| 1 | "Uh, so, we, um, agreed on Friday." | "So, we agreed on Friday." | hesitations out, discourse word kept |
| 2 | "We were- we're shipping next week." | "We're shipping next week." | false start dropped |
| 3 | "It costs two hundred and fifty dollars." | "It costs $250." or "It costs 250 dollars." | digits; the scorer reads `$250` as "250 dollars" |
| 4 | "The twenty-second of June." | "The 22nd of June." | digits for dates |
| 5 | "Me and him went to the client." | "Me and him went to the client." | the speaker's grammar stays |
| 6 | "Like, the numbers are, like, fine." | "Like, the numbers are, like, fine." | discourse "like" is a word |
| 7 | "Palantir's CEO, Alex Karp, said…" | "Palantir's CEO, Alex Karp, said…" | two entity spans, `accept: ["Palantir's"]` |
| 8 | "Growth was three point five percent." | "Growth was 3.5%." | digits for amounts |
| 9 | Speaker unintelligible for one word | "We sent it to [?] yesterday." | `[?]`, rest of the line kept |
| 10 | 30 s of hold music on a call | no text | `non_speech` kind `music` |

### Ukrainian

| # | Heard | Reference | Rule |
|---|---|---|---|
| 1 | "Ем, ну, ми вже, е, домовилися." | "Ну, ми вже домовилися." | hesitations out; "ну" is a word |
| 2 | "Ми пере- ми переносимо зустріч." | "Ми переносимо зустріч." | false start dropped |
| 3 | "Дата — двадцять друге червня." | "Дата — 22 червня." | digits for dates; span kind `date` |
| 4 | "Це коштує п'ятсот гривень." | "Це коштує 500 гривень." | digits for amounts |
| 5 | "Дві тисячі двадцять шостого року." | "2026 року." | digits for years |
| 6 | "Петро надішле цифри до п’ятниці." | "Петро надішле цифри до п'ятниці." | one apostrophe (`'`); the scorer folds ’ ʼ into it |
| 7 | "Ми говорили з Петром Іваненком." | "Ми говорили з Петром Іваненком." | entity `text: "Петро Іваненко"`, `accept: ["Петром Іваненком"]` |
| 8 | "Він сказав: *deadline is Friday*." | "Він сказав:" (uk) + "Deadline is Friday." (en) | split at the switch; `code_switch` region |
| 9 | Russian or surzhyk words inside Ukrainian speech | written as spoken, inside the `uk` segment | the speaker's words stay; the gold set's languages are de/uk/en only |
| 10 | Jingle, then "Дякую за увагу." spoken by the host | no text for the jingle; "Дякую за увагу." | spoken sign-off is speech, not an artefact |

## 6. What a labeller never does

- Correct the speaker's facts, names or grammar.
- Copy text from another product's transcript of the same audio. Engine-v2
  decision 8 forbids this unless counsel clears it.
- Write a person's name into `speaker` or into the manifest.
- Commit anything under `eval/asr/` except `manifest.json` and `README.md`.
