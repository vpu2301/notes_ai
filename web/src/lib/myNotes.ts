// The author's scratchpad: records when each new line first appeared in the
// recording. Line identity is the server's `sha256(normalise(text)).hex[:16]`.
// Never changes the author's text.

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

/** `sha256(normalise(stripBullet(text))).hex[:16]`, or "" for a blank line. */
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
 * Collects `{line_key, offset_ms}` for lines not seen before, stamped with
 * the recording clock. An edited line is a new key; the server keeps the first.
 */
export class LineTimeQueue {
  private readonly seen = new Set<string>();
  private pending: LineTime[] = [];
  /** Observations are chained so they cannot interleave. */
  private tail: Promise<void> = Promise.resolve();

  constructor(private readonly elapsedMs: () => number) {}

  /** Call on every change of the scratchpad text. */
  observe(text: string): Promise<void> {
    // Clock read now, not when the hash comes back.
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

export const MERGE_DIVIDER = "---";

/** Append local lines under a divider, never overwrite; lines the server has are skipped. */
export function mergeScratch(remote: string, local: string): string {
  if (!local.trim()) return remote;
  if (!remote.trim()) return local;
  if (remote === local) return remote;
  const have = new Set(splitLines(remote).map((line) => normalise(stripBullet(line))));
  const fresh = splitLines(local).filter((line) => !have.has(normalise(stripBullet(line))));
  if (fresh.length === 0) return remote;
  return `${remote.replace(/\s+$/, "")}\n\n${MERGE_DIVIDER}\n${fresh.join("\n")}`;
}
