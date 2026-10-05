import type { CoverageGap, CoverageGapCause, TranscriptCoverage } from "../api/types";

/**
 * Sprint F1: "Not transcribed: 00:00–00:44 (audio started late), …" — the
 * speech the transcript is missing, and why, as the worker measured it.
 * Pure, so the wording is testable without a page.
 */

export const MAX_SHOWN_GAPS = 4;

const REASONS: Record<CoverageGapCause, string> = {
  no_audio: "audio started late",
  no_speech_detected: "no speech detected",
  decoder_empty: "could not be decoded",
  prompt_echo: "could not be decoded",
  unknown: "could not be decoded",
  other_language: "another language",
  backend_error: "the transcriber did not answer",
};

/** mm:ss, or h:mm:ss from an hour on. */
export function clock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${String(m).padStart(2, "0")}:${ss}`;
}

export interface GapItem {
  /** "00:00–00:44 (audio started late)" */
  text: string;
  startMs: number;
  /** A `no_audio` gap precedes the file: there is nothing to open. */
  seekable: boolean;
}

export function gapReason(cause: string): string {
  return REASONS[cause as CoverageGapCause] ?? REASONS.unknown;
}

export function gapItems(gaps: readonly CoverageGap[]): GapItem[] {
  return [...gaps]
    .sort((a, b) => (a.cause === "no_audio" ? -1 : b.cause === "no_audio" ? 1 : a.start_ms - b.start_ms))
    .map((g) => ({
      text: `${clock(g.start_ms)}–${clock(g.end_ms)} (${gapReason(g.cause)})`,
      startMs: g.start_ms,
      seekable: g.cause !== "no_audio",
    }));
}

/** What the line shows: up to four ranges and how many more there are. */
export function notTranscribed(
  coverage: TranscriptCoverage | null | undefined,
): { shown: GapItem[]; more: number } | null {
  const items = gapItems(coverage?.gaps ?? []);
  if (items.length === 0) return null;
  const shown = items.slice(0, MAX_SHOWN_GAPS);
  return { shown, more: items.length - shown.length };
}

/** The whole line as plain text (copy, tests, screen readers). */
export function notTranscribedLine(coverage: TranscriptCoverage | null | undefined): string | null {
  const line = notTranscribed(coverage);
  if (!line) return null;
  const ranges = line.shown.map((i) => i.text).join(", ");
  return `Not transcribed: ${ranges}${line.more > 0 ? ` +${line.more} more` : ""}`;
}
