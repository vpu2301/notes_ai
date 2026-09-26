// Sprint I2: the transcript as text to copy, and the diagnostics line.
//
// Pure so the page does not have to render for these to be tested.

import type { TranscriptResult, TranscriptTurn } from "../api/types";
import { mmss } from "./generation";

/** A turn spoken in another language than the recording ("uk" in an English one). */
export function isOtherLanguage(turn: Pick<TranscriptTurn, "language">): boolean {
  return typeof turn.language === "string" && turn.language.length > 0;
}

/**
 * The transcript as plain text: `Name: paragraphs` per turn when speakers
 * were told apart, else the paragraphs alone. Turns in another language
 * than the recording are left out unless asked for — they are the passage
 * a listener would not have followed either, and in a copy meant for
 * someone else they read as noise.
 */
export function transcriptCopyText(
  turns: TranscriptTurn[],
  nameOf: (turn: TranscriptTurn) => string,
  options: { diarized: boolean; includeOtherLanguages: boolean },
): string {
  return turns
    .filter((t) => options.includeOtherLanguages || !isOtherLanguage(t))
    .map((t) => {
      const body = t.paragraphs.join("\n");
      return options.diarized ? `${nameOf(t)}: ${body}` : body;
    })
    .join("\n\n");
}

/**
 * "12 words removed as prompt echo at 00:03, 01:40" — or null when nothing
 * was removed. The transcriber repeating its own prompt over silence is
 * taken out by the worker; this says so, once, where the words would have
 * been.
 */
export function promptEchoLine(diagnostics: TranscriptResult["diagnostics"] | undefined): string | null {
  const echoes = diagnostics?.prompt_echo ?? [];
  if (echoes.length === 0) return null;
  const words = echoes.reduce((sum, e) => sum + e.words, 0);
  const at = [...echoes].sort((a, b) => a.start_ms - b.start_ms).map((e) => mmss(e.start_ms));
  return `${words} ${words === 1 ? "word" : "words"} removed as prompt echo at ${at.join(", ")}`;
}
