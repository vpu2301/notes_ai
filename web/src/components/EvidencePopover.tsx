import { useEffect, useRef, useState } from "react";
import { createClip, dateCalendarFile } from "../api/generation";
import { ApiError } from "../api/http";
import { messageFor } from "../lib/errorCopy";
import type { GeneratedItem } from "../api/types";
import { mmss } from "../lib/generation";
import { provenanceLabel } from "../i18n/note";

/** Certainty chip label; a plain fact has no chip. */
export const CERTAINTY_LABELS: Record<string, string> = {
  prediction: "Forecast",
  estimate: "Estimate",
  opinion: "Opinion",
  proposal: "Proposal",
  allegation: "Allegation",
  reported: "Claim",
  unproven: "Claim — unsubstantiated",
  refuted: "Claim — refuted",
};

/** Seconds of recording played either side of the quote. */
export const CLIP_PADDING_MS = 1_500;

/** The server refuses longer clips (MDX_CLIP_MAX_SPAN_MS); a long line plays from its start. */
export const CLIP_MAX_SPAN_MS = 60_000;

/** "Forecast · Reinbold" — or null for a plain fact. */
export function chipLabel(row: GeneratedItem): string | null {
  const label = row.certainty ? CERTAINTY_LABELS[row.certainty] : undefined;
  if (!label) return null;
  const holder = row.attributed_to?.split(/\s+/).pop();
  return holder ? `${label} · ${holder}` : label;
}

/** Evidence behind a generated line: verbatim quote, time, speaker, play button.
 *  Members only — never on the shared page, client version or PDF. */
export function LineEvidence({
  noteId,
  row,
  rowsByKey,
  language,
}: {
  noteId: string;
  row: GeneratedItem;
  rowsByKey?: Map<string, GeneratedItem>;
  /** The note's language (B4): the provenance chip is written in it. */
  language?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const wrap = useRef<HTMLSpanElement>(null);
  const chip = chipLabel(row);
  const corrected = (row.corrections ?? []).filter((c) => c.canonical !== c.surface);
  const others = (row.cites ?? []).slice(1);
  // B4: "Wörtlich" / "Paraphrase" / "Aus 2 Aussagen" — what the line is, never a judgement.
  const provenance = provenanceLabel(language, row.provenance, (row.cites ?? []).length);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  // May sit inside a click-to-edit document: nothing here may start editing.
  const stop = (e: { stopPropagation: () => void }) => e.stopPropagation();

  const play = async () => {
    setProblem(null);
    setPlaying(true);
    try {
      const start = Math.max(0, row.start_ms - CLIP_PADDING_MS);
      const end = Math.min(row.end_ms + CLIP_PADDING_MS, start + CLIP_MAX_SPAN_MS);
      const url = await createClip(noteId, start, end);
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      await audio.play();
    } catch (err) {
      setProblem(err instanceof ApiError && err.status === 410 ? "Recording no longer available" : messageFor(err));
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
      setProblem(messageFor(err));
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
        {/* The mark is CSS-drawn so copying a line never carries it along. */}
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
          {provenance && <span className="provenance-chip muted">{provenance}</span>}
          {row.verdict && <span className="verdict-line">{row.verdict}</span>}
          <q className="evidence-quote">{row.quote}</q>
          <span className="evidence-meta muted">
            {provenance ? `${provenance} · ` : ""}
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
