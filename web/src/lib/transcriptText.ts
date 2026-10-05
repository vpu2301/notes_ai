// Sprint I2: the transcript as text to copy, and the diagnostics line.
//
// Pure so the page does not have to render for these to be tested.

import type { TranscriptNoise, TranscriptResult, TranscriptTurn } from "../api/types";
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
  options: {
    diarized: boolean;
    includeOtherLanguages: boolean;
    /** Sprint TQ2: `[Music 00:12–00:41]` lines, only when asked for. */
    markers?: { noise: TranscriptNoise[]; language: string | null | undefined };
  },
): string {
  const lines: { at: number; text: string }[] = turns
    .filter((t) => options.includeOtherLanguages || !isOtherLanguage(t))
    .map((t) => {
      const body = t.paragraphs.join("\n");
      return { at: t.start_ms, text: options.diarized ? `${nameOf(t)}: ${body}` : body };
    });
  if (options.markers) {
    for (const n of options.markers.noise) {
      lines.push({ at: n.start_ms, text: markerLine(n, options.markers.language) });
    }
  }
  return lines
    .sort((a, b) => a.at - b.at)
    .map((l) => l.text)
    .join("\n\n");
}

/**
 * Sprint TQ2: what a non-speech marker is called, in the language that was
 * spoken. A kind this build does not know is noise (the field is additive).
 */
export const MARKER_LABELS: Record<string, Record<"music" | "silence" | "noise", string>> = {
  en: { music: "Music", silence: "Silence", noise: "Noise" },
  de: { music: "Musik", silence: "Stille", noise: "Geräusch" },
  uk: { music: "Музика", silence: "Тиша", noise: "Шум" },
};

export function markerKind(kind: string): "music" | "silence" | "noise" {
  return kind === "music" || kind === "silence" ? kind : "noise";
}

/** "[Musik 00:12–00:41]" */
export function markerLine(n: TranscriptNoise, language: string | null | undefined): string {
  const labels = MARKER_LABELS[language ?? ""] ?? { music: "Music", silence: "Silence", noise: "Noise" };
  return `[${labels[markerKind(n.kind)]} ${mmss(n.start_ms)}–${mmss(n.end_ms)}]`;
}

/**
 * The markers to show before turn `index` (those starting before it and at
 * or after the previous turn); `index === turns.length` gives the ones
 * after the last turn. Markers never become turns: selection, focus and
 * moves keep addressing turns by position.
 */
export function markersBefore(
  noise: TranscriptNoise[] | undefined,
  turns: Pick<TranscriptTurn, "start_ms">[],
  index: number,
): TranscriptNoise[] {
  if (!noise || noise.length === 0) return [];
  const lo = index === 0 ? -Infinity : (turns[index - 1]?.start_ms ?? -Infinity);
  const hi = index >= turns.length ? Infinity : (turns[index]?.start_ms ?? Infinity);
  return noise.filter((n) => n.start_ms >= lo && n.start_ms < hi);
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
