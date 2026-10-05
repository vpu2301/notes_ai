// The transcript tab's wording for the server's spelling overlay. Pure.

import type { EntityCorrection } from "../api/types";

type Lang = "en" | "de" | "uk";

const WORDS: Record<Lang, {
  unified: (n: number) => string;
  toReview: (n: number) => string;
  review: string;
  from: string;
}> = {
  en: {
    unified: (n) => `${n} ${n === 1 ? "spelling" : "spellings"} unified`,
    toReview: (n) => `${n} ${n === 1 ? "spelling" : "spellings"} to review`,
    review: "Review",
    from: "unified from",
  },
  de: {
    unified: (n) => `${n} ${n === 1 ? "Schreibweise" : "Schreibweisen"} vereinheitlicht`,
    toReview: (n) => `${n} ${n === 1 ? "Schreibweise" : "Schreibweisen"} zu prüfen`,
    review: "Prüfen",
    from: "vereinheitlicht aus",
  },
  uk: {
    unified: (n) => `Уніфіковано написань: ${n}`,
    toReview: (n) => `Написань на перевірку: ${n}`,
    review: "Переглянути",
    from: "уніфіковано з",
  },
}; // prettier-ignore

function words(language: string | null | undefined) {
  return WORDS[(language ?? "") as Lang] ?? WORDS.en;
}

/** The banner over the transcript, or null. Counts variant spellings, not clusters. */
export function correctionsBanner(
  corrections: EntityCorrection[] | undefined,
  language: string | null | undefined,
): { text: string; action: string } | null {
  const live = (corrections ?? []).filter(needsReview);
  if (live.length === 0) return null;
  const w = words(language);
  const unified = live.filter((c) => c.status === "accepted").reduce((n, c) => n + c.from_forms.length, 0);
  const proposed = live.filter((c) => c.status === "proposed").reduce((n, c) => n + c.from_forms.length, 0);
  const parts = [unified > 0 ? w.unified(unified) : null, proposed > 0 ? w.toReview(proposed) : null];
  return { text: parts.filter(Boolean).join(" · "), action: w.review };
}

/** Not rejected and not yet decided. */
export function needsReview(c: EntityCorrection): boolean {
  return c.status !== "rejected" && !c.decided;
}

/** "vereinheitlicht aus: Andala, Handela" */
export function unifiedFromTitle(c: EntityCorrection, language: string | null | undefined): string {
  return `${words(language).from}: ${c.from_forms.join(", ")}`;
}

export interface TextPart {
  text: string;
  /** Set on a span an accepted correction produced. */
  correction?: EntityCorrection;
}

/** A paragraph split into plain text and accepted-correction spans (whole words only). */
export function unifiedParts(paragraph: string, corrections: EntityCorrection[] | undefined): TextPart[] {
  const accepted = (corrections ?? []).filter((c) => c.status === "accepted" && c.to_text.trim());
  if (accepted.length === 0) return [{ text: paragraph }];
  const escaped = accepted
    .map((c) => c.to_text)
    .sort((a, b) => b.length - a.length)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`(?<![\\p{L}\\p{N}])(${escaped.join("|")})(?![\\p{L}\\p{N}])`, "gu");
  const out: TextPart[] = [];
  let last = 0;
  for (const m of paragraph.matchAll(re)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ text: paragraph.slice(last, at) });
    out.push({ text: m[0], correction: accepted.find((c) => c.to_text === m[0]) });
    last = at + m[0].length;
  }
  if (last < paragraph.length) out.push({ text: paragraph.slice(last) });
  return out;
}
