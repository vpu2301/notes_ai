import { useEffect, useRef, useState } from "react";
import { createClip, dateCalendarFile } from "../api/generation";
import { ApiError, errorMessage } from "../api/http";
import type { GeneratedItem } from "../api/types";
import { mmss } from "../lib/generation";

/** What a line's certainty is called on its chip (Summary Engine v2, Q5).
 *  A plain fact has no chip. */
export const CERTAINTY_LABELS: Record<string, string> = {
  prediction: "Forecast",
  estimate: "Estimate",
  opinion: "Opinion",
  proposal: "Proposal",
  allegation: "Allegation",
};

/** Seconds of recording played either side of the quote. */
export const CLIP_PADDING_MS = 1_500;

/** "Forecast · Reinbold" — or null for a plain fact. */
export function chipLabel(row: GeneratedItem): string | null {
  const label = row.certainty ? CERTAINTY_LABELS[row.certainty] : undefined;
  if (!label) return null;
  const holder = row.attributed_to?.split(/\s+/).pop();
  return holder ? `${label} · ${holder}` : label;
}

/**
 * The evidence behind one generated line, opened from the line itself.
 *
 * The quote (verbatim, as the transcriber heard it), when it was said and
 * by whom, and a button that plays the recording around it. Labels are
 * data from the row, drawn here — never words in the note a person would
 * have to edit around. Members only: this is never rendered on the shared
 * page, the client version or the PDF.
 */
export function LineEvidence({
  noteId,
  row,
  rowsByKey,
}: {
  noteId: string;
  row: GeneratedItem;
  rowsByKey?: Map<string, GeneratedItem>;
}) {
  const [open, setOpen] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const wrap = useRef<HTMLSpanElement>(null);
  const chip = chipLabel(row);
  const corrected = (row.corrections ?? []).filter((c) => c.canonical !== c.surface);
  const others = (row.cites ?? []).slice(1);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  // The line may sit inside a click-to-edit document: nothing here may
  // start editing.
  const stop = (e: { stopPropagation: () => void }) => e.stopPropagation();

  const play = async () => {
    setProblem(null);
    setPlaying(true);
    try {
      const url = await createClip(noteId, row.start_ms - CLIP_PADDING_MS, row.end_ms + CLIP_PADDING_MS);
      await new Audio(url).play();
    } catch (err) {
      setProblem(err instanceof ApiError && err.status === 410 ? "Recording no longer available" : errorMessage(err));
    } finally {
      setPlaying(false);
    }
  };

  const download = async () => {
    try {
      const blob = await dateCalendarFile(noteId, row.item_key);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${row.item_key}.ics`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setProblem(errorMessage(err));
    }
  };

  return (
    <span className="line-evidence" ref={wrap} onClick={stop} onKeyDown={stop}>
      {chip && <span className="certainty-chip">{chip}</span>}
      {corrected.map((c) => (
        <span key={c.surface} className="name-chip" title={`heard as: ${c.surface}`}>
          {c.canonical}
        </span>
      ))}
      {row.kind === "date" && (
        <button type="button" className="icon-btn date-ics" aria-label="Add to calendar" onClick={() => void download()}>
          📅
        </button>
      )}
      <button
        type="button"
        className="icon-btn evidence-toggle"
        aria-label="Show where this came from"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
      >
        ❝
      </button>
      {open && (
        <span
          className="evidence-popover"
          role="dialog"
          aria-label="Evidence"
          onKeyDown={(e) => {
            if (e.key === "Escape") setOpen(false);
          }}
        >
          {chip && <span className="certainty-chip">{chip}</span>}
          <q className="evidence-quote">{row.quote}</q>
          <span className="evidence-meta muted">
            {mmss(row.start_ms)}
            {row.speaker_name ? ` · ${row.speaker_name}` : ""}
          </span>
          <button type="button" className="btn sm" disabled={playing} onClick={() => void play()}>
            {playing ? "Playing…" : "Play"}
          </button>
          {problem && <span className="evidence-problem">{problem}</span>}
          {others.length > 0 && (
            <span className="evidence-more">
              and {others.length} more:
              <ul>
                {others.map((key) => (
                  <li key={key}>{rowsByKey?.get(key)?.text ?? "another statement from the recording"}</li>
                ))}
              </ul>
            </span>
          )}
        </span>
      )}
    </span>
  );
}
