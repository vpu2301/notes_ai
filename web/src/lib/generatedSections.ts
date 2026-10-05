/**
 * Which sections the engine wrote (`gen:` keys, or generation rows in them),
 * so the "<word>: " speaker-turn rule is off there ("Vorwurf: …" is not a speaker).
 */
export const GENERATED_PREFIX = "gen:";

export function generatedSectionKeys(rows: ReadonlyArray<{ section_key: string }>): Set<string> {
  return new Set(rows.map((r) => r.section_key));
}

export function isGeneratedSection(key: string, keys: ReadonlySet<string>): boolean {
  return key.startsWith(GENERATED_PREFIX) || keys.has(key);
}
