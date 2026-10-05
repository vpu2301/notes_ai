import { useState } from "react";
import { rememberTerm } from "../api/glossary";
import { messageFor } from "../lib/errorCopy";
import { isVocabulary } from "../lib/glossaryRule";
import { useToast } from "./Toaster";

export interface PendingTerm {
  /** The spelling the author chose. */
  term: string;
  /** What it had been heard as; empty when there was no previous name. */
  heardAs: string;
  /** The note the rename happened in, when the caller knows it. */
  noteId?: string;
}

/** "Remember *John Mayer* for this workspace?" — offered once after a rename; never learned silently. */
export function RememberTermPrompt({
  pending,
  onDone,
}: {
  pending: PendingTerm | null;
  onDone: () => void;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (!pending) return null;
  // A role label ("Moderator II") is not a name; the server would refuse it.
  if (!isVocabulary(pending.term, "person")) return null;

  const remember = async () => {
    setBusy(true);
    try {
      await rememberTerm({
        term: pending.term,
        kind: "person",
        heard_as: pending.heardAs ? [pending.heardAs] : [],
        ...(pending.noteId ? { note_id: pending.noteId } : {}),
      });
      toast.success(`We'll spell "${pending.term}" that way from now on`);
      onDone();
    } catch (err) {
      toast.error(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="banner banner-info remember-term" role="status">
      <span className="grow">
        Send &quot;<strong>{pending.term}</strong>&quot; to the transcriber for every recording in
        this workspace?
      </span>
      <button className="btn ghost sm" disabled={busy} onClick={onDone}>
        Not now
      </button>
      <button className="btn primary sm" disabled={busy} onClick={() => void remember()}>
        Remember
      </button>
    </div>
  );
}

// Characters the server refuses in a term, as code-point ranges (half are invisible):
//   0000-001F, 007F-009F controls; 200B-200F zero-width/LRM/RLM;
//   2028-202E separators, bidi embedding; 2066-2069 bidi isolates.
const FORBIDDEN: ReadonlyArray<readonly [number, number]> = [
  [0x0000, 0x001f],
  [0x007f, 0x009f],
  [0x200b, 0x200f],
  [0x2028, 0x202e],
  [0x2066, 0x2069],
];

function hasForbidden(text: string): boolean {
  for (const ch of text) {
    const code = ch.codePointAt(0)!;
    if (FORBIDDEN.some(([lo, hi]) => code >= lo && code <= hi)) return true;
  }
  return false;
}

const PLACEHOLDER = /^speaker\s*\d+$/i;

/** Whitespace collapsed, as the server stores it. */
function normalise(name: string): string {
  return name.trim().split(/\s+/).join(" ");
}

/** Only a real correction is offered: not a reset to "Speaker 2", nor a case/spacing change. */
export function isWorthRemembering(from: string, to: string): boolean {
  const term = normalise(to);
  if (term.length < 2 || term.length > 80) return false;
  if (PLACEHOLDER.test(term)) return false;
  if (normalise(from).toLocaleLowerCase() === term.toLocaleLowerCase()) return false;
  // The server refuses these.
  return !hasForbidden(term);
}

/** What the old name should be recorded as, if anything. */
export function heardAsOf(from: string): string {
  const previous = normalise(from);
  return PLACEHOLDER.test(previous) || previous.length < 2 ? "" : previous;
}
