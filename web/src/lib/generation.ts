import type { ExcludedRange } from "../api/types";

/**
 * What the engine left out of a note, in words (Summary Engine v2, Q3).
 *
 * The engine used to write "Hinweis zum Transkript: … wurde nicht
 * berücksichtigt." into the note itself — a paragraph the rich-text
 * renderer took for a speaker called "HT". Exclusions are now data on the
 * generation (`excluded_ranges`), and these labels — a closed vocabulary,
 * in the language that was spoken — are the only words for them.
 */
export const NOISE_LABELS: Record<string, Record<string, string>> = {
  en: {
    background: "background speech",
    other_language: "a passage in another language",
    artifact: "a transcription artifact",
    duplicate: "a duplicated passage",
    unrelated: "an unrelated fragment",
    advertisement: "an advertisement",
    music: "music",
    noise: "noise",
  },
  de: {
    background: "Hintergrundgespräch",
    other_language: "eine Passage in einer anderen Sprache",
    artifact: "ein Transkriptionsartefakt",
    duplicate: "eine doppelte Passage",
    unrelated: "ein unzusammenhängendes Fragment",
    advertisement: "Werbung",
    music: "Musik",
    noise: "Geräusche",
  },
  uk: {
    background: "фонова мова",
    other_language: "уривок іншою мовою",
    artifact: "артефакт транскрипції",
    duplicate: "повторений уривок",
    unrelated: "непов'язаний фрагмент",
    advertisement: "реклама",
    music: "музика",
    noise: "шум",
  },
};

/** Ranges shown before "+N more". */
export const MAX_SHOWN_RANGES = 4;

export function mmss(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

export interface ExcludedItem {
  startMs: number;
  text: string;
}

/** `00:45–00:52 (background speech)`, in the note's language, in time order. */
export function excludedItems(ranges: ExcludedRange[], language?: string | null): ExcludedItem[] {
  const labels: Record<string, string> = NOISE_LABELS[language ?? ""] ?? NOISE_LABELS.en ?? {};
  return [...ranges]
    .sort((a, b) => a.start_ms - b.start_ms)
    .map((r) => ({
      startMs: r.start_ms,
      text: `${mmss(r.start_ms)}–${mmss(r.end_ms)} (${labels[r.reason] ?? labels.unrelated ?? r.reason})`,
    }));
}

/** What the recording was taken to be, for the pill that replaces the
 *  template name. `meeting` has no label: the template name stays. */
export const RECORDING_TYPE_LABELS: Record<string, string> = {
  client_call: "Client call",
  sales_call: "Sales call",
  interview: "Interview",
  one_on_one: "One-on-one",
  podcast_broadcast: "Podcast / broadcast",
  lecture_webinar: "Lecture / webinar",
  presentation_demo: "Presentation / demo",
  voice_memo: "Voice memo",
};

export function recordingTypeLabel(recordingType?: string | null): string | null {
  if (!recordingType || recordingType === "meeting") return null;
  return RECORDING_TYPE_LABELS[recordingType] ?? null;
}
