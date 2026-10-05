// What may go into the workspace glossary (the transcriber's prompt): speaker
// role labels ("Moderator II") were once echoed into a transcript, so they never
// reach it. Tables mirror tests/fixtures/glossary/role_words.json (asserted equal)
// and note_service.domain.glossary.is_vocabulary.

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
 * Vocabulary (a name, company, product, word) rather than a voice label:
 * no tokens, all role words/ordinals ("Moderator II"), or an all-lowercase person → not vocabulary.
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
