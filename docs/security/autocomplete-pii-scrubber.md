# Autocomplete PII Scrubber Specification

## Purpose

The autocomplete service captures telemetry that ranks phrases.
Prefixes posted from the FE may inadvertently contain personal data
(names alongside emails, phone numbers, ID or card numbers). This
scrubber redacts them BEFORE persistence — raw prefixes never touch
disk (scrub-before-store).

Privacy review of the regex set is required before ship and on every
regex change thereafter.

## Patterns redacted

| name        | regex                                                                     | replacement      | rationale                                                        |
| ----------- | ------------------------------------------------------------------------- | ---------------- | ---------------------------------------------------------------- |
| email       | `\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b`                                        | `<redacted_PII>` | obvious PII                                                      |
| card_like   | `(?<![\d-])(?:\d[ -]?){12,18}\d(?!\d)`                                    | `<redacted_PII>` | credit-card-like: 13-19 digits, optional space/dash grouping     |
| national_id | `\b[A-Za-z]{1,3}\s?\d{6,9}\b`                                             | `<redacted_PII>` | national-ID-like: standalone 1-3 letter prefix + 6-9 digits      |
| phone       | `(?<![\d+])(?:\+\d{7,15}\|\+?\(?\d{1,4}\)?(?:[ .-]\d{2,4}){2,5})(?!\d)`   | `<redacted_PII>` | `+` international form, or 3+ separator-broken digit groups      |
| digit_run   | `(?<!\d)\d{7,}(?!\d)`                                                     | `<redacted_PII>` | catch-all: any unbroken run of 7+ digits (phones, tax/account #) |

The set is deliberately generic — no locale-specific ID formats
(exact-length national tax/ID/passport patterns from earlier versions
are subsumed by `digit_run` and `national_id`).

## Behaviour

- Order-sensitive: more-specific patterns first (`card_like` before
  `phone` before the `digit_run` sweep) so redaction counts stay
  attributed to the most specific class.
- All matches replaced with the literal `<redacted_PII>` placeholder
  (no per-pattern variants — uniform downstream surface).
- Conservative bias: false positives (over-scrubbing) preferred over
  false negatives (PII leak). Known over-scrub: date-shaped strings
  with 2+-digit components (`01.02.2026`) are eaten by the `phone`
  pattern — accepted, DOB-style dates are PII anyway.
- Known limitation: two separator-broken digit groups (`2026 2027`)
  are NOT caught — the `phone` pattern requires 3+ groups so ordinary
  business numerics (year ranges, "10 30" times) survive.

## Revision history

- **2026-09-01** — pattern set replaced wholesale for the horizontal
  product: locale-specific classes (`ipn`, `med_id`, `passport`,
  `dob_like`) removed; generic `card_like`, `national_id` and
  `digit_run` added; `phone` extended to separator-broken groups
  (`050 123 45 67`), previously a documented gap. **Pending privacy
  re-review** per the policy below.
- **2026-07-07** — `phone` widened to catch international `+…` forms
  that fell between the old exact-length patterns and leaked
  (observed live in the dev stack).

## Call sites

1. **Telemetry intake** (`autocomplete_service.routers.telemetry`):
   prefix + context fields scrubbed before the buffer accepts the row.
2. **Phrase/snippet write** (`autocomplete_service.routers.phrases`):
   `contains_pii` is run on the user-supplied text; any match →
   422 + `autocomplete.phrase.write_rejected_pii` audit event
   (pattern names and text length only — never the matched text).

## Test corpus

`services/autocomplete-service/tests/unit/test_scrubber.py` exercises
each pattern plus the safe-text negatives; it grows as privacy review
surfaces new patterns.

## Privacy sign-off log

| date       | reviewer | change                                   | status  |
| ---------- | -------- | ---------------------------------------- | ------- |
| pending    | privacy  | generic pattern set (2026-09-01 rewrite) | pending |

Any regex change requires a new row above + a re-review of the test
corpus.
