// Sprint I2: what may go into the workspace glossary.
//
// The glossary is the prompt the transcriber is given before every
// recording. The 2026-09-25 incident put speaker role labels in it
// ("Moderator II", "moderatorin", "narrator", "speaker background") and
// Whisper echoed them into a transcript. A label a person gave a voice is
// not a spelling worth teaching, so it never reaches the list.
//
// The tables below are the one list every client and the server read:
// tests/fixtures/glossary/role_words.json at the repo root. The vitest
// suite asserts they are equal, so they cannot drift. The rule mirrors
// note_service.domain.glossary.is_vocabulary.

import type { GlossaryKind } from "../api/types";

export const ROLE_WORDS: Readonly<Record<string, readonly string[]>> = {
  en: [
    "speaker",
    "moderator",
    "host",
    "narrator",
    "guest",
    "interviewer",
    "interviewee",
    "presenter",
    "caller",
    "background",
    "unknown",
    "voice",
    "participant",
    "translator",
    "announcer",
  ],
  de: [
    "sprecher",
    "sprecherin",
    "moderator",
    "moderatorin",
    "gast",
    "gastgeber",
    "erzähler",
    "erzählerin",
    "hintergrund",
    "unbekannt",
    "stimme",
    "teilnehmer",
    "teilnehmerin",
    "übersetzer",
  ],
  uk: [
    "спікер",
    "ведучий",
    "ведуча",
    "гість",
    "гостя",
    "оповідач",
    "фон",
    "невідомий",
    "голос",
    "учасник",
    "учасниця",
    "перекладач",
  ],
};

export const ROLE_WORDS_ALL: ReadonlySet<string> = new Set(Object.values(ROLE_WORDS).flat());

export const ORDINALS: ReadonlySet<string> = new Set([
  "i",
  "ii",
  "iii",
  "iv",
  "v",
  "1",
  "2",
  "3",
  "4",
  "5",
  "one",
  "two",
  "three",
  "eins",
  "zwei",
  "drei",
  "один",
  "два",
  "три",
  "first",
  "second",
  "erste",
  "zweite",
  "перший",
  "другий",
]);

// Word tokens: runs of letters and digits, any script. Python's `[^\W_]+`.
const TOKEN = /[\p{L}\p{N}]+/gu;
const UPPER = /^\p{Lu}/u;

function tokens(term: string): string[] {
  return (term.match(TOKEN) ?? []).map((t) => t.toLocaleLowerCase());
}

/**
 * Whether a term is vocabulary — a name, a company, a product, a word —
 * rather than a label for a voice.
 *
 * - no word tokens → not vocabulary
 * - every token a role word (any language) or an ordinal → not vocabulary
 *   ("Moderator II", "speaker background", "Sprecher 2")
 * - a person whose parts all start lowercase → not vocabulary ("moderatorin")
 */
export function isVocabulary(term: string, kind: GlossaryKind): boolean {
  const words = tokens(term);
  if (words.length === 0) return false;
  if (words.every((w) => ROLE_WORDS_ALL.has(w) || ORDINALS.has(w))) return false;
  if (kind === "person") {
    const parts = term.trim().split(/\s+/);
    if (!parts.some((p) => UPPER.test(p))) return false;
  }
  return true;
}
