// The author's scratchpad, client side (Sprint 34).
//
// While the meeting runs, the first keystroke of every new line is worth
// remembering: it is what later tells the engine WHERE in the recording to
// look for what the line is about. The line's identity is the same hash the
// server and the action-item projection use —
// `sha256(normalise(text)).hex[:16]` — so a line keeps its timing across a
// whitespace edit, and the same line typed on two devices is one line.
//
// Nothing here ever changes the author's text. It only observes it.

import type { LineTime } from "../api/types";

/** Mirrors `action_items.normalise_text` on the server, exactly. */
function normalise(text: string): string {
  return text
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[.;,]+$/, "")
    .trim()
    .toLowerCase();
}

/** Mirrors `user_notes._strip_bullet`: the marker is not part of the line. */
function stripBullet(text: string): string {
  return text.replace(/^[\s\-•*·▪◦]*(?:\d{1,2}[.)]\s*)?[\s\-•*·]*/, "");
}

/**
 * `sha256(normalise(stripBullet(text))).hex[:16]`, or "" for a blank line.
 *
 * Async because WebCrypto is: the queue below awaits it off the typing
 * path, so hashing never sits between a keystroke and the character
 * appearing.
 */
export async function lineKey(text: string): Promise<string> {
  const normalised = normalise(stripBullet(text));
  if (!normalised) return "";
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(normalised));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 16);
}

/** The non-blank lines of the scratchpad, in order. */
export function splitLines(text: string): string[] {
  return text.split("\n").filter((line) => line.trim() !== "");
}

/**
 * Watches the scratchpad and collects `{line_key, offset_ms}` for lines it
 * has not seen before.
 *
 * The clock is the recording's, not the wall's: `elapsedMs()` is asked at
 * the moment the line first appears, so a line typed at 2:10 into the
 * meeting is stamped 130000 whatever the device's clock says.
 *
 * Only NEW keys are emitted. Editing a line gives it a new key and a new
 * (later) time, which is correct — the author was thinking about it then
 * too — and the server keeps whichever arrived first.
 */
export class LineTimeQueue {
  private readonly seen = new Set<string>();
  private pending: LineTime[] = [];
  /** Hashing is async; observations are chained so they cannot interleave
   *  and a flush can wait for the ones already in flight. */
  private tail: Promise<void> = Promise.resolve();

  constructor(private readonly elapsedMs: () => number) {}

  /** Call on every change of the scratchpad text. */
  observe(text: string): Promise<void> {
    // The clock is read NOW, not when the hash comes back: the line
    // appeared at this moment in the recording.
    const at = Math.max(0, Math.round(this.elapsedMs()));
    this.tail = this.tail.then(async () => {
      for (const line of splitLines(text)) {
        const key = await lineKey(line);
        if (!key || this.seen.has(key)) continue;
        this.seen.add(key);
        this.pending.push({ line_key: key, offset_ms: at });
      }
    });
    return this.tail;
  }

  /** Resolves once every observation so far has been keyed. */
  settled(): Promise<void> {
    return this.tail;
  }

  /** Everything collected since the last drain; empties the queue. */
  drain(): LineTime[] {
    const out = this.pending;
    this.pending = [];
    return out;
  }

  /** Put a failed flush back, oldest first, so nothing is lost on a blip. */
  requeue(lines: LineTime[]): void {
    this.pending = [...lines, ...this.pending];
  }

  get size(): number {
    return this.pending.length;
  }
}

/**
 * Merge scratch text typed on this device into what the server already has.
 *
 * Append under a divider, never overwrite: two devices typing the same
 * meeting is two people's worth of attention on it, and silently dropping
 * one of them is the one failure this feature cannot have. Lines the server
 * already holds are skipped, so a reconnect does not duplicate.
 */
export const MERGE_DIVIDER = "---";

export function mergeScratch(remote: string, local: string): string {
  if (!local.trim()) return remote;
  if (!remote.trim()) return local;
  if (remote === local) return remote;
  const have = new Set(splitLines(remote).map((line) => normalise(stripBullet(line))));
  const fresh = splitLines(local).filter((line) => !have.has(normalise(stripBullet(line))));
  if (fresh.length === 0) return remote;
  return `${remote.replace(/\s+$/, "")}\n\n${MERGE_DIVIDER}\n${fresh.join("\n")}`;
}
