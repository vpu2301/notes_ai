/**
 * Sprint SQ3 T1 — which note sections the engine wrote.
 *
 * A generated paragraph never opens with a speaker label, but older notes
 * have "Gast: Felix …" lines, and a certainty word ("Vorwurf: …") used to
 * open a summary sentence. The rich-text renderer reads "<word>: " at the
 * start of a paragraph as a transcript turn and draws an avatar
 * ("VVorwurf"), so in a generated section that rule is off. A section is
 * generated when the engine named it (`gen:` keys) or when this note's
 * generation rows sit in it. Derived from data the page already has: no
 * new route.
 */
export const GENERATED_PREFIX = "gen:";

export function generatedSectionKeys(rows: ReadonlyArray<{ section_key: string }>): Set<string> {
  return new Set(rows.map((r) => r.section_key));
}

export function isGeneratedSection(key: string, keys: ReadonlySet<string>): boolean {
  return key.startsWith(GENERATED_PREFIX) || keys.has(key);
}
