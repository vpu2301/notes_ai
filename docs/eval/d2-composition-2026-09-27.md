# Sprint D2 — composition to the standard, first measurements (2026-09-27)

**Built:** blocks and budget, phase headings and quote children, subjects and narrator attribution,
the roles table and type cues, orientation ladders, scorers and gates (ADR-0066).
**Not measured:** acceptance 2 needs `eval/notes/v2` (not on this machine); the blind rubric
needs raters.

## Acceptance 1 — r03 on the stack model (Gemma 3 4B, temperature 0)

| Item | Result |
|---|---|
| "Podcast-Folge" | **met.** The classifier said lecture; the cues (show word, clips, advert) made it a podcast. |
| No presenter | **met.** The narrator is `narrator`, the trailer voice `clip`. |
| No label or pronoun subjects | **met** after repair: the linter removed the one label line. |
| Themes in paragraph 1 | **met**: five themes, cleaned from the model's packed, quoted list. |
| 6–8 sections in episode order | **not met**: one section. Of three blocks, one got a model heading; two had no statement to restate or to chapter. |
| ≥ 90 % specific bullets, ≥ 3 sub-points | **not met**: one bullet, no sub-points. |
| Guest line "Felix Holtermann (Handelsblatt)" | **not met**: the model extracted no introduction, and the roles table names a guest only from one. |
| Thiel's view attributed to Thiel | **not tested**: no fact with that view was extracted. |
| Volume in band | **not met.** |
| Blind rubric ≥ 13/16 | **not run.** |

Checklist: 22 of 40, unchanged from D1's run, with the type check now passing. The limit is
the extraction: 16 of 25 kept facts are verbatim copies (evidence only). The model never fills
`subject`. Its block bullets are mostly refused for naming people their block does not say
(9 lines).

## What the run changed in the engine

- **"UNKNOWN" is never a participant.** The diarizer's catch-all label holds trailer voices and
  sound bites.
- **Themes arrive packed** into one quoted string ("Datensammlung”, „Geheimdienste”, …) and are
  split, unquoted, and their cut last piece dropped.
- **A name another fact of the block says is cited, not refused.** Code adds that fact to the
  bullet's citations; at most two are added.
- **German names are told from nouns by their company.** A frequent capitalised word counts as a
  name when it mostly appears without an article, number or inflected adjective before it. On r03:
  Alex, Felix, Karp, Peter, Thiel, USA, Valley — not Menschen, Gebäude, Ende, Unternehmen. Blocks,
  fallback headings and the linter read the same set.

## Scripted stand-in

All scripted checklists still pass (m06 11/11, m09 4/4, m10 5/5, m11 4/4, r03 17/17 gated).
