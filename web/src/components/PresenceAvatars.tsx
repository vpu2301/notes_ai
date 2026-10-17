import type React from "react";
import { useEffect, useState } from "react";
import { getPresence, heartbeatPresence } from "../api/notes";
import type { PresenceViewer } from "../api/types";
import { speakerInitials, speakerTint } from "../lib/speakers";

/** Heartbeat and re-read on one timer while the tab is visible; the server forgets a viewer 45 s after their last beat. */
export const PRESENCE_MS = 20_000;
const SHOWN = 3;

/** "Anna is viewing", "Anna and Tom are viewing", "Anna and 2 others are viewing". */
export function presenceLabel(viewers: PresenceViewer[]): string {
  const [first, second] = viewers;
  if (!first) return "";
  if (viewers.length === 1) return `${first.display_name} is viewing`;
  if (viewers.length === 2 && second) return `${first.display_name} and ${second.display_name} are viewing`;
  return `${first.display_name} and ${viewers.length - 1} others are viewing`;
}

/** Who else has this note open. Fails quiet: no answer is no one. */
export function PresenceAvatars({ noteId }: { noteId: string }) {
  const [viewers, setViewers] = useState<PresenceViewer[]>([]);

  useEffect(() => {
    let live = true;
    // A hidden tab is not "viewing": no heartbeat, no reads, until it is shown again.
    const visible = () => document.visibilityState === "visible";
    const tick = async () => {
      if (!visible()) return;
      await heartbeatPresence(noteId).catch(() => undefined);
      try {
        const next = await getPresence(noteId);
        if (live) setViewers(next);
      } catch {
        if (live) setViewers([]);
      }
    };
    const onVisibility = () => void tick();
    void tick();
    const timer = window.setInterval(() => void tick(), PRESENCE_MS);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      live = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [noteId]);

  if (viewers.length === 0) return null;
  const label = presenceLabel(viewers);
  return (
    <span className="presence" role="status" aria-label={label} title={label}>
      {viewers.slice(0, SHOWN).map((v) => (
        <span
          key={v.sub}
          className="speaker-avatar presence-avatar"
          style={{ "--tint": speakerTint(v.display_name) } as React.CSSProperties}
          aria-hidden="true"
        >
          {speakerInitials(v.display_name)}
        </span>
      ))}
      {viewers.length > SHOWN && <span className="presence-more" aria-hidden="true">+{viewers.length - SHOWN}</span>}
    </span>
  );
}
