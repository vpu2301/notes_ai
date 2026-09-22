import { useState } from "react";
import { rememberTerm } from "../api/glossary";
import { errorMessage } from "../api/http";
import { useToast } from "./Toaster";

export interface PendingTerm {
  /** The spelling the author chose. */
  term: string;
  /** What it had been heard as; empty when there was no previous name. */
  heardAs: string;
}

/**
 * "Remember *John Mayer* for this workspace?" — offered once, after the
 * author fixes a name.
 *
 * The offer is the design. A vocabulary that learned silently would, the
 * first time it learned something wrong, quietly mis-spell a customer's
 * name in every note afterwards with nobody able to say why. So: one
 * term, one question, and an answer the author gives.
 */
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

  const remember = async () => {
    setBusy(true);
    try {
      await rememberTerm({
        term: pending.term,
        kind: "person",
        heard_as: pending.heardAs ? [pending.heardAs] : [],
      });
      toast.success(`We'll spell "${pending.term}" that way from now on`);
      onDone();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="banner banner-info remember-term" role="status">
      <span className="grow">
        Remember <strong>{pending.term}</strong> for this workspace? We&apos;ll give the
        spelling to the transcriber before your next recording.
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

// Characters a term may not contain — the same set the server refuses.
// Built from code-point RANGES rather than written as a literal class:
// half of them are invisible, and a source file that contains a bidi
// override in order to reject bidi overrides is one nobody can review.
//
//   0000-001F, 007F-009F  C0 / C1 controls
//   200B-200F             zero-width space, joiners, LRM/RLM
//   2028-202E             line/paragraph separators, bidi embedding
//   2066-2069             bidi isolates
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

/** Whitespace collapsed, exactly as the server stores it — so a rename
 *  that only changes the spacing compares as no change. */
function normalise(name: string): string {
  return name.trim().split(/\s+/).join(" ");
}

/**
 * Whether a rename is worth offering to remember.
 *
 * Only a real correction: the author typed a name where there was a
 * placeholder or a different name. A name cleared back to "Speaker 2", or
 * one that only changed case or spacing, teaches nothing.
 */
export function isWorthRemembering(from: string, to: string): boolean {
  const term = normalise(to);
  if (term.length < 2 || term.length > 80) return false;
  if (PLACEHOLDER.test(term)) return false;
  if (normalise(from).toLocaleLowerCase() === term.toLocaleLowerCase()) return false;
  // The server refuses these; not offering them at all is friendlier
  // than a toast explaining why.
  return !hasForbidden(term);
}

/** What the old name should be recorded as, if anything. */
export function heardAsOf(from: string): string {
  const previous = normalise(from);
  return PLACEHOLDER.test(previous) || previous.length < 2 ? "" : previous;
}
