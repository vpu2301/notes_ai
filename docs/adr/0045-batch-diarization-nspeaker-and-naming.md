# ADR-0045: Batch diarization — N-speaker agglomerative clustering, word-level attribution, speaker naming

Date: 2026-09-02
Status: Accepted
Amends: ADR-0034 (batch path only; the streaming clusterer is unchanged)

## Context

A podcast recorded from the desktop app came back as a good transcript
and a bad note: one block of text, no speakers. Three separate causes,
found in one pass:

1. **The result endpoint dropped the speakers.** `GET /asr/jobs/{id}/result`
   rebuilt every segment for NLP enrichment and never copied the
   `speaker` field or the `speakers` roster onto the view. The worker
   had diarized the job; nothing downstream could tell. Every client and
   the note builder saw an undiarized transcript.
2. **The offline clusterer was the streaming clusterer.** `diarize_offline`
   fed the whole recording through the online 2-slot bootstrap of
   ADR-0034 — a pilot cap accepted for live sessions, where the second
   speaker must be found before the meeting ends. A batch job holds
   every embedding up front; capping it at two voices meant a host with
   two guests got `SPEAKER_1`, `SPEAKER_2`, and UNKNOWN for the third.
3. **Attribution was per Whisper segment.** Whisper splits on its own
   pause heuristics; a segment routinely spans "…that's the plan. —
   Sounds good." from two people, and majority-overlap attribution
   labelled the reply with whoever spoke longer.

On top of that, even a correctly diarized job reached the note as
`SPEAKER_1: …` lines with no way to say who `SPEAKER_1` was except by
editing text, and nothing tied the web app's guess to the desktop app's.

## Decision

### Result view carries the structure (asr-service)

`_enriched_result_view` keeps `speaker` on every segment through both
the raw and the NLP-enriched paths (a punctuation-only segment merged
into its predecessor inherits the predecessor's speaker), keeps the
roster, and finishes the view with two additive fields:

- `speaker_names`: label → display name for every roster label — the
  person's name if one was set, else the neutral default `Speaker N`.
- `turns`: the transcript as speaker turns with paragraphs, built by
  `asr_models.structure.build_turns` — consecutive same-speaker
  segments form a turn; an unattributed segment between two runs of the
  same speaker is absorbed (mid-sentence dropout), otherwise it stands
  alone as an unattributed turn; inside a turn a paragraph breaks at a
  ≥1.5 s pause once it has ~160 chars, at a sentence end past ~600, and
  unconditionally past ~1000. One implementation, rendered by the web
  app, the macOS app, and `POST /v1/notes/from-transcript`.

### Offline clustering: average-linkage agglomerative (libs/diarization)

`diarize_offline` embeds every ≤1.2 s chunk as before, then clusters
globally: average-linkage agglomeration on cosine similarity, cut at
`link_threshold = 0.45` — the same same-voice/cross-voice boundary
ADR-0034 measured (same-voice ≥ ~0.5, cross ≤ ~0.45). Chunk-level
similarity is noisy, so one voice can come out as a main cluster plus
outlier side clusters; a second pass merges clusters whose *centroids*
are ≥ 0.60 alike (centroids average the noise out — two clusters of one
voice sit near 0.9, two voices near 0.1–0.3). Guards: a cluster needs
≥ 2 chunks and ≥ 1 % of the recording to be a speaker, the roster is
capped at 8, and every chunk is then scored against the surviving
centroids with the streaming rule (floor 0.45, ambiguity margin 0.08 →
UNKNOWN). Above 1500 chunks the clusters are learnt on an evenly spaced
sample and all chunks are scored against the centroids, so a 3-hour
recording stays bounded. Pure numpy, no randomness (agglomeration with
per-row best-partner tracking, O(n²)), ties break on stream order;
`SPEAKER_N` numbering is by first appearance.

The streaming path keeps the online clusterer — the constraints that
justified it have not changed.

### Word-level attribution (asr-worker)

`_apply_diarization` attributes each word (the worker already requests
word timings) and splits a segment wherever the speaker changes; each
piece keeps its own words, timing and mean word probability. Smoothing:
unattributed words take their neighbours' label when the neighbours
agree (or the one known neighbour at a segment edge); a one-word island
between two runs of the same speaker folds back. What stays
unattributed keeps `speaker=None`. The stored roster is the labels that
actually reached a segment, so "3 speakers" means three findable in the
text.

### Speaker naming (asr-service, both apps)

`PUT /asr/jobs/{id}/speakers` with `{"names": {"SPEAKER_2": "Olena"}}`
stores the complete label → name map on the job row (migration 0018,
`speaker_names jsonb`). Labels must be neutral `SPEAKER_N`; names are
whitespace-collapsed, ≤ 80 chars; an empty name clears the label back
to its default. Audited as `asr.speakers_named` with the labels only.
The next read of the result merges the names into `speaker_names` and
`turns`.

Clients: clicking a speaker's name in the transcript tab turns it into a
text field; Return saves. While the note is still a draft the app also
rewrites `Old: ` → `New: ` at the start of turn lines in the note body
(the shape `from-transcript` writes) and autosaves. A finalized note is
a record and keeps its text; only the transcript shows the new name.
Names are never inferred server-side (ADR-0034 posture unchanged).

## Consequences

- A diarized batch job is visibly diarized everywhere, for any number of
  speakers up to 8; a name given in one app appears in the other and in
  notes created afterwards.
- The note body format changed from `SPEAKER_1: text` lines to
  `Speaker 1: paragraph` blocks separated by blank lines (paragraphs of a
  turn on following lines). Existing notes are untouched.
- Batch and live diarization of the same audio may now disagree beyond
  two speakers — expected, and the live path's documented limitation.
- The DER harness (`scripts/eval/run_der.py`) exercises the streaming
  path; a batch re-baseline on `eval/conversations/v1` plus a ≥3-speaker
  fixture is the follow-up gate before this is called measured rather
  than calibrated. Synthetic check at authoring time (192-d unit
  vectors, 4 voices, 2–8 chunk turns, laptop CPU):

  | chunks | same-voice cos | cross cos | speakers found | UNKNOWN | purity | time |
  |---|---|---|---|---|---|---|
  | 1981 | 0.59 | 0.01 | 4 | 0 % | 1.000 | 0.5 s |
  | 1981 | 0.48 | 0.01 | 4 | 0 % | 1.000 | 0.5 s |
  | 1981 | 0.39 | 0.01 | 4 | 0 % | 1.000 | 6.3 s |
  | 9029 | 0.48 | 0.01 | 4 | 0 % | 1.000 | 0.5 s (sampled) |

  Without the centroid merge the 0.48 row came out as 8 "speakers"
  (four real, four outlier clusters of 3–5 chunks) with 7 % UNKNOWN —
  which is why the pass exists. Synthetic cross-voice similarity is
  optimistic; real ECAPA cross-voice sits at 0.1–0.4, near-twin voices
  remain the ADR-0034 limitation.
