# Smoke-eval meetings (DEP-S0)

Five **synthetic** business-meeting transcripts written for the smoke eval —
no real people, companies or audio. They are not a gold set (that arrives
with the BE-S2 corpus); they exist so `make eval-smoke BACKEND=…` can prove
a backend returns schema-valid, evidence-bearing JSON in EN / DE / UK.

Each file: `{ id, language, transcript: [{speaker, t_start_ms, t_end_ms, text}],
expect: { min_action_items, must_mention: [...] } }`. `must_mention` are
substrings the extraction must quote verbatim from the transcript (the
evidence check); anything quoted that is *not* in the transcript counts as
a hallucination.
