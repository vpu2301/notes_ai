# Notes gold set `eval/notes/v2` (Sprint SQ1)

The same recordings as `eval/asr/v1`, with the same ids and the same consent. A
summary number and a transcript number then always refer to the same audio. One
meeting file per recording lives in the private eval bucket
(`s3://notes-eval/notes/v2/<id>.json`, eval role), never in git:

- `transcript`: the ASR snapshot, from the production path at the pinned engine
- `reference_transcript`: the human-corrected transcript (TQ1 `reference.json`)
- `gold`: format v3, with `key_facts` {id, text, third, kind, holder}, `participants`
  {label, name, role, speech_share}, `opinions`, `topic_segments`, `non_content`,
  `title_reference` and `reviewers`

```
make eval-notes-validate CORPUS=eval/notes/v2
make eval-notes BACKEND=<backend> ARM=pipeline CORPUS=eval/notes/v2
```

**Status (2026-10-01): empty.** The owner decided not to label a gold set for now
and to judge notes on real recordings instead. The routing decision is ADR-0068. The CI waiver is in
`docs/eval/routing-waivers.yaml`.
