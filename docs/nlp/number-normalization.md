# Number & Unit Normalization

Pipeline Stage 3 transforms spelled-out and hybrid number expressions
into canonical short form. **Per-language rule-based** (ADR-0015).

## Coverage matrix

| Pattern              | UK example                                | EN example                       | DE example                              | Output                       |
| -------------------- | ----------------------------------------- | -------------------------------- | --------------------------------------- | ---------------------------- |
| Paired reading (`X на Y` / `X over Y` / `X zu Y`) | `тиск сто двадцять на вісімдесят` | `pressure one twenty over eighty` | `Druck hundertvierzig zu neunzig` | `тиск 120/80` / `pressure 120/80` / `Druck 140/90` |
| Paired reading with units | `… міліметрів ртутного стовпчика`    | `… millimeters of mercury`       | `… Millimeter Quecksilbersäule`         | `… мм рт. ст.` / `… mmHg`    |
| Rate                 | `пульс сімдесят два за хвилину`           | `pulse 72 bpm`                   | `Puls achtzig pro Minute`               | `пульс 72/хв` / `pulse 72 bpm` / `Puls 80/min` |
| Amount + unit        | `п'ять міліграм`                          | `five milligrams`                | `fünf Milligramm`                       | `5 мг` / `5 mg`              |
| Decimal              | `сім цілих п'ять`                         | `seven point five`               | `sieben Komma fünf`                     | `7,5` (UK/DE) / `7.5` (EN)   |
| Range                | `від ста до ста двадцяти`                 | `from one hundred to one twenty` | `von zehn bis zwanzig Milliliter`       | `100–120` / `10–20 ml`       |
| Time (half-past)     | `о пів на восьму`                         | `half past seven`                | `halb acht` (Stage 4)                   | `07:30`                      |
| Frequency            | `три рази на добу`                        | `three times a day`              | `dreimal täglich`                       | `3 разів/добу` / `3x/day` / `3x/Tag` |
| Generic NUM+UNIT     | `двадцять мілілітрів`                     | `twenty milliliters`             | `zwanzig Milliliter`                    | `20 мл` / `20 ml`            |

The measurement patterns (paired readings, rates, dose-style amounts)
are legacy vocabulary from the dictation heritage; they are kept
because they are exactly the shapes any measurement-heavy dictation
(site inspections, lab-style notes, logistics) produces.

## Per-tenant configuration

`tenants.settings` (admin UI surfaces these):

- `decimal_separator`: `","` (UK + DE default) or `"."` (EN default).
- `bp_separator`: separator for paired readings, `"/"` default.
- `date_format` (Stage 4): `"DD.MM.YYYY"` / `"YYYY-MM-DD"` / `"WORD"`.

## Untagged numbers

A number with no surrounding unit/pattern marker is **passed through
unchanged**. "один клієнт" stays "один клієнт" — the parser refuses
to fold a single bare digit-word to "1" because the determiner is
meaningful as text.

Spelled-out cardinals with ≥ 2 words DO fold even without a unit
nearby ("сто двадцять одна" → "121") because at that length the
parser's interpretation is unambiguous.

## English colloquial pairs

"one twenty" (heard when dictating a reading of 120) is normalized to
`120` by a colloquial-form heuristic: if the head is a single digit
(1–9) followed by a tens digit (10–90) with no `hundred`/`thousand` in
between, treat as `head*100 + tens`. The standard form
"one hundred twenty" still works through the regular parser.

**The colloquial reading is trusted only inside an explicit paired
(`over`) or range (`from … to`) structure.** A standalone "two ten" or
"one twenty" is too ambiguous to fold and **passes through unchanged** —
the heuristic must never fabricate a number (e.g. "two ten" → `210`)
outside an explicit numeric structure (ADR-0015).

## German compound numerals

German writes a whole numeral as ONE token and puts the unit before the
ten: "vierundzwanzig" is 24 (*four-and-twenty*), "einhundertfünfund­vierzig"
is 145. The parser is therefore word-internal, splitting on
`tausend` → `hundert` → `und` rather than walking a token run.

Folding follows the same pass-through-on-doubt rule as English, applied
to the German shape: a numeral is written as digits when a unit follows
it, when the rate/frequency phrase disambiguates it (`pro Minute`,
`dreimal täglich`), or when the numeral is itself a compound. A bare
"acht" stays "acht" — "der Gast kam um acht" is prose.

The paired-reading separator is `zu` (also `auf`), which is one of the
most common prepositions in the language, so the gate matters more here
than in UK/EN: "drei zu vier" passes through untouched.

## Figure-safety gating (ADR-0015)

The safety mandate is *pass-through-on-doubt*: a wrong figure is worse
than an un-normalized one. Two rules carry the weight:

- **The paired-reading slash (`NUM на NUM` / `NUM over NUM` → `N/M`)**
  is emitted only when there is a real signal: a trailing unit
  (`мм рт. ст.` / `mmHg`), a preceding cue word (`тиск` · `pressure`),
  **or** both numbers fall in the plausible paired ranges (60–300 /
  30–160). Otherwise `на`/`over` is left as text, so
  "три на чотири" / "five over four" pass through unchanged.
- **Decimal fractions** are rendered digit-by-digit, preserving leading
  zeros: "два цілих нуль п'ять" → `2,05` (never `2,0`), "five point zero
  five" → `5.05` (never `5.5`). A dropped fractional digit silently
  corrupts a dictated figure.

## Known limitations

- Ukrainian genitive plural endings on units ("п'ять міліграмів")
  collapse to the canonical short ("5 мг") — case info is lost.
- Cross-language switching mid-text is not supported.
- Ordinals (Ukrainian declensions) have partial support for the common
  forms; the long tail is on the regression list.
- German ordinals live in Stage 4 (dates); the number stage does not
  fold them. Austrian/Swiss variants beyond `Jänner` and `ss`-for-`ß`
  are not covered.

## Latency budget

p95 ≤ 10 ms on a 50-word segment (rule-based; no model calls).
