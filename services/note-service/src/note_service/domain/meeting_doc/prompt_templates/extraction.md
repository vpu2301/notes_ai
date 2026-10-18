Extract distinct, useful propositions from the supplied transcript window. Each proposition must cite the exact original-language evidence required by the supplied schema.

Read the surrounding turns before resolving pronouns, conditions or quoted speech. If the necessary context is outside this window, mark the proposition for reconciliation using the supported fields rather than guessing. Do not reconstruct missing speech.

For each proposition, preserve:
- acoustic speaker when known from the supplied metadata;
- the quoted or reported holder of the position, if explicitly supported;
- the subject being discussed, which is not necessarily the position holder;
- the full operative condition, recipient, amount, time and negation;
- the source's actual degree of certainty and commitment.

The host's characterization and a person's direct statement are different evidence. A rhetorical introduction must not replace a later precise quote. For example, a promise to pay every adult citizen if a party wins both chambers must not become a promise to pay each person for their vote. Extract the direct promise with its condition and recipients. Preserve a host's interpretation as a separate attributed interpretation only if useful.

Do not label a foreign-language passage as noise. If the schema includes a noise field, use it only for genuinely unrelated background content, non-speech artifacts or genuine duplicated transcript artifacts as allowed by the schema. Repeated discussion with a clarification is not a duplicate artifact.

Use only the provided proposition kinds. A politician promising an action is not a team action item. Preparation already undertaken is not merely a proposal. A comparison must preserve both compared entities. Unknown names remain unknown; speaker IDs are identifiers, not personal names.

Avoid extracting several paraphrases of the same proposition within this window. Keep distinct conditions, opposing positions and corrections separate for reconciliation. Prefer informative propositions over greetings, filler and scene-setting that adds no substantive content.
