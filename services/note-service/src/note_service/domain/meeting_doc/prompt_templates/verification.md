Assess whether each candidate claim is semantically supported by the supplied original evidence and adjacent context. Compare meaning across languages when necessary. A lexical word match or valid citation ID does not prove support.

For each claim check actor, statement holder versus subject, recipient, condition, amount/unit, time, negation, direction of comparison and modality. Check that all independently asserted parts have evidence. Do not judge political or factual truth using outside knowledge; judge fidelity to the source and its attribution.

Use:
- supported: all material parts follow from the supplied evidence;
- contradicted: the claim conflicts with the evidence or changes a material condition, recipient, actor, quantity, negation or comparison;
- insufficient_evidence: the provided evidence does not establish the claim, including unresolved context or attribution.

A faithful translation can be supported even with no shared content words. Fluent prose can be contradicted. Missing an operative condition is material, not merely stylistic.

Return the supplied claim_id, verdict, exact evidence IDs and a short explanation of the decisive mismatch or support. Supply a minimal corrected_claim only when the evidence unambiguously supports it; otherwise null. Do not treat a proposed correction as verified: the caller must check it again. Do not invent evidence IDs or rewrite source quotes.
