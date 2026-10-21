import { useEffect, useRef, useState } from "react";
import { createClip, dateCalendarFile } from "../api/generation";
import { ApiError } from "../api/http";
import { messageFor } from "../lib/errorCopy";
import type { CitedTurn, GeneratedItem } from "../api/types";
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

/** The turns a line cites (P3), or, from an older server, the row's own quote as one turn. */
export function citedTurns(row: GeneratedItem): CitedTurn[] {
  if (row.cited_turns && row.cited_turns.length > 0) return row.cited_turns;
  if (!row.cites || row.cites.length === 0) return [];
  return [
    {
      turn: -1,
      start_ms: row.start_ms,
      end_ms: row.end_ms,
      speaker: row.speaker_name ?? null,
      text: row.quote,
    },
  ];
}

/** Evidence behind a generated line: the cited turns, time, speaker, play and seek.
 *  Members only — never on the shared page, client version or PDF.
 *  A line without a cite shows a grey "no reference" mark and opens nothing. */
export function LineEvidence({
  noteId,
  row,
  rowsByKey,
  language,
  onSeek,
}: {
  noteId: string;
  row: GeneratedItem;
  rowsByKey?: Map<string, GeneratedItem>;
  /** The note's language (B4): the provenance chip is written in it. */
  language?: string | null;
  /** Opens the transcript at a moment (P3: "Show in transcript"). */
  onSeek?: (ms: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const wrap = useRef<HTMLSpanElement>(null);
  const chip = chipLabel(row);
  const corrected = (row.corrections ?? []).filter((c) => c.canonical !== c.surface);
  const turns = citedTurns(row);
  const first = turns[0];
  // Older rows cite fact keys; the popover names those lines instead of turns.
  const factCites = row.cited_turns?.length ? [] : (row.cites ?? []).slice(1);
  // B4: "Wörtlich" / "Paraphrase" / "Aus 2 Aussagen" — what the line is, never a judgement.
  const provenance = provenanceLabel(language, row.provenance, (row.cites ?? []).length);
  const unsupported = row.check === "unsupported";

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
    if (!first) return;
    setProblem(null);
    setPlaying(true);
    try {
      const start = Math.max(0, first.start_ms - CLIP_PADDING_MS);
      const end = Math.min(first.end_ms + CLIP_PADDING_MS, start + CLIP_MAX_SPAN_MS);
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
      {turns.length === 0 ? (
        // No cite: a grey mark that says so and opens nothing.
        <span className="evidence-dot none" role="img" aria-label="No reference" title="No reference" />
      ) : (
        <button
          type="button"
          className={`icon-btn evidence-toggle${unsupported ? " unsupported" : ""}`}
          aria-label={unsupported ? "Show where this came from (not found in the transcript)" : "Show where this came from"}
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setOpen(false);
          }}
        >
          {/* The mark is CSS-drawn so copying a line never carries it along. */}
        </button>
      )}
      {open && first && (
        <span
          className="evidence-popover"
          role="dialog"
          aria-label="Evidence"
          onKeyDown={(e) => {
            if (e.key === "Escape") setOpen(false);
          }}
        >
          {unsupported && (
            <span className="evidence-check" role="note">
              Not found in the transcript
              {row.check_reason ? ` — ${row.check_reason}` : ""}
            </span>
          )}
          {chip && <span className="certainty-chip">{chip}</span>}
          {provenance && <span className="provenance-chip muted">{provenance}</span>}
          {row.cite_nearest && <span className="provenance-chip muted">Nearest match</span>}
          {row.verdict && <span className="verdict-line">{row.verdict}</span>}
          <ul className="evidence-turns">
            {turns.map((t, i) => (
              <li key={`${t.turn}-${i}`} className={i === 0 ? "first" : undefined}>
                <span className="evidence-meta muted">
                  <mark className="evidence-time">{mmss(t.at_ms ?? t.start_ms)}</mark>
                  {t.speaker ? ` · ${t.speaker}` : ""}
                  {t.excerpt ? " · part of a longer turn" : ""}
                </span>
                <q className="evidence-quote">{t.text}</q>
              </li>
            ))}
          </ul>
          <span className="evidence-actions">
            <button type="button" className="btn sm" disabled={playing} onClick={() => void play()}>
              {playing ? "Playing…" : "Play"}
            </button>
            {onSeek && (
              <button
                type="button"
                className="btn sm ghost"
                onClick={() => {
                  setOpen(false);
                  onSeek(first.start_ms);
                }}
              >
                Show in transcript
              </button>
            )}
          </span>
          {problem && <span className="evidence-problem">{problem}</span>}
          {factCites.length > 0 && (
            <span className="evidence-more">
              and {factCites.length} more:
              <ul>
                {factCites.map((key) => (
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
