import { Fragment, createElement, type ReactNode } from "react";

/** Speaker-correction strings as whole sentences with `{placeholders}`: never concatenate a name or number. */
export const SPEAKER_COPY = {
  suggestionGroup: "Name suggestion for {speaker}",
  suggestionLead: "Probably {name}",
  suggestionQuote: "“{quote}”",
  suggestionQuoteLabel: "“{quote}” — show this at {time} in the transcript",
  suggestionAccept: "Accept",
  suggestionAcceptLabel: "Accept {name} for {speaker}",
  suggestionDismiss: "Dismiss suggestion",
  suggestedMarker: "suggested",
  suggestedMarkerLabel: "Name suggested from the conversation",
  acceptedUndo: "{speaker} is now {name}",
  acceptFailed: "Couldn't name {speaker}: {reason}",
  dismissFailed: "Couldn't dismiss the suggestion: {reason}",
  relabelOffer: "Speakers were detected with an older method. Re-label? Your speaker names are kept where possible.",
  relabelOfferAction: "Re-label",
  relabelOfferLater: "Not now",
  chipMenuLabel: "{name} — rename or merge",
  chipMenuLabelSuggested: "{name} (suggested) — rename or merge",
  removeChannelName: "Remove the name {name}",
  announceMerged: "Merged",
  announceMovedOne: "Moved 1 turn",
  announceMovedMany: "Moved {count} turns",
  announceRelabelled: "Re-labelling finished",
  announceRelabelUndone: "Re-labelling undone",
  announceNamed: "Named {name}",
  announceUndone: "Undone",
  announcementsRegion: "Speaker updates",
} as const;

export type SpeakerCopyKey = keyof typeof SPEAKER_COPY;

const PLACEHOLDER = /\{(\w+)\}/g;

/** A copy string with its `{placeholders}` filled in as text. */
export function copyText(key: SpeakerCopyKey, vars: Record<string, string | number> = {}): string {
  return SPEAKER_COPY[key].replace(PLACEHOLDER, (m, k: string) => (k in vars ? String(vars[k]) : m));
}

/** A copy string with its placeholders filled in by React nodes. */
export function copyNodes(key: SpeakerCopyKey, vars: Record<string, ReactNode>): ReactNode {
  const parts = SPEAKER_COPY[key].split(PLACEHOLDER);
  // split() with a capture group alternates text, name, text, name, …
  return parts.map((part, i) =>
    i % 2 === 1 ? createElement(Fragment, { key: i }, part in vars ? vars[part] : `{${part}}`) : part,
  );
}

/** "Moved 1 turn" / "Moved 3 turns". */
export function movedAnnouncement(count: number): string {
  return count === 1 ? copyText("announceMovedOne") : copyText("announceMovedMany", { count });
}
