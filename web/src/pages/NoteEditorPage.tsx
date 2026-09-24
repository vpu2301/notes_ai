import React, { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  dismissNameSuggestion,
  getResult,
  listJobs,
  mergeSpeakers,
  reassignTurns,
  setSpeakerNames,
  undoSpeakerEdit,
} from "../api/asr";
import { ApiError, errorMessage } from "../api/http";
import {
  deleteNote,
  downloadPdf,
  getItems,
  getNote,
  getResponses,
  getTemplate,
  getVersion,
  listVersions,
  needsReadPurpose,
  notesBySourceJob,
  updateDraft,
} from "../api/notes";
import type {
  FieldMetadata,
  ItemView,
  NameSource,
  NameSuggestion,
  ResponseView,
  NoteContent,
  NoteEnvelope,
  NoteSection,
  NoteVersionDetail,
  NoteVersionSummary,
  ReadPurpose,
  SpeakerNameSource,
  TemplateSection,
  TranscriptResult,
  TranscriptTurn,
} from "../api/types";
import { defaultSpeakerName } from "../api/types";
import { AskNote } from "../components/AskNote";
import { CarriedItems } from "../components/CarriedItems";
import { GenerationStatus } from "../components/GenerationStatus";
import { DocTypePill } from "../components/DocTypePill";
import { ClientVersionPanel } from "../components/ClientVersion";
import { ConfirmDialog } from "../components/ConfirmDialog";
import {
  RememberTermPrompt,
  heardAsOf,
  isWorthRemembering,
  type PendingTerm,
} from "../components/RememberTermPrompt";
import { ResponsesPanel } from "../components/ResponsesPanel";
import {
  AlertIcon,
  ArrowLeftIcon,
  CalendarIcon,
  CheckIcon,
  CopyIcon,
  DownloadIcon,
  FileDownIcon,
  FolderIcon,
  FolderPlusIcon,
  HistoryIcon,
  ShareIcon,
  TrashIcon,
  UserIcon,
} from "../components/icons";
import { Menu, type MenuItem } from "../components/Menu";
import { RichText, type LineExtra } from "../components/RichText";
import { LineEvidence } from "../components/EvidencePopover";
import { CorrectionsPanel } from "../components/CorrectionsPanel";
import { useGeneratedLines } from "../lib/useGeneratedLines";
import { lineKey } from "../lib/itemKey";
import type { GeneratedItem } from "../api/types";
import { isTranscript, parseRichText } from "../lib/richText";
import { messageFor } from "../lib/errorCopy";
import { pickableNames, segmentIndicesOf, speakerInitials, speakerTint } from "../lib/speakers";
import { SpeakerRoster, useOnline } from "../components/SpeakerRoster";
import { NameSuggestionChip } from "../components/NameSuggestionChip";
import { copyText, movedAnnouncement } from "../i18n/speakers";
import { ShareDialog } from "../components/ShareDialog";
import { Skeleton } from "../components/Skeleton";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toaster";
import { useAuth } from "../auth/AuthContext";
import { jobForNote, rememberLink } from "../lib/captures";
import { noteToMarkdown, safeFilename, saveBlob } from "../lib/exportNote";
import { formatDateTime, formatElapsed, relativeTime } from "../lib/time";
import { defFor, noteBlocks } from "../lib/noteBlocks";
import { useDismiss } from "../lib/useDismiss";
import { useSpaces } from "../spaces/SpacesContext";

const AUTOSAVE_MS = 900;

type SaveState = "saved" | "dirty" | "saving" | "error";

/** Read a section (by key) out of content, or an empty shell. */
function sectionOf(content: NoteContent, key: string): NoteSection {
  return content.sections?.find((s) => s.section_key === key) ?? { section_key: key };
}

/** Immutably upsert one section in the content. */
function withSection(content: NoteContent, next: NoteSection): NoteContent {
  const sections = content.sections ? [...content.sections] : [];
  const i = sections.findIndex((s) => s.section_key === next.section_key);
  if (i >= 0) sections[i] = next;
  else sections.push(next);
  return { ...content, sections };
}

/**
 * Manual-entry metadata per the note_models contract: user-entered values
 * carry source:"manual" and no confidence; an empty dict means "no value".
 */
function manualMeta(values: Record<string, unknown> | null): FieldMetadata {
  if (values === null || Object.keys(values).length === 0) return {};
  return { ...values, source: "manual" };
}

function metaValue<T>(meta: FieldMetadata | undefined, key: string): T | undefined {
  if (!meta) return undefined;
  return meta[key] as T | undefined;
}

// ── field editors ─────────────────────────────────────────────────────

interface FieldProps {
  def: TemplateSection;
  section: NoteSection;
  readOnly: boolean;
  onChange: (next: NoteSection) => void;
  /** Q5: the evidence of a generated line, drawn at its end. */
  lineExtra?: LineExtra;
}

/**
 * One free-text section.
 *
 * A note is a document first: what the model wrote is typeset — headings,
 * nested bullets, checklists — rather than dumped as the raw `- ` and
 * `**…**` a plain box used to show. On a draft the document is also the
 * way in: click it and the same words come back as their markdown source
 * in a seamless editor, and leaving the field sets them again. A section
 * with nothing in it skips straight to the editor — there is no document
 * to read yet, only a prompt to write one.
 */
function FreeTextField({ def, section, readOnly, onChange, lineExtra }: FieldProps) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [editing, setEditing] = useState(false);
  const text = section.text ?? "";
  const placeholder = def.min_chars ? `At least ${def.min_chars} characters…` : "Start writing…";

  // Auto-grow to fit content.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [text, editing]);

  // Put the caret at the end, not at the start of the text we just typeset.
  const onFocusEditor = (e: React.FocusEvent<HTMLTextAreaElement>) => {
    const end = e.target.value.length;
    e.target.setSelectionRange(end, end);
  };

  if (readOnly) return <RichText text={text} lineExtra={lineExtra} />;

  if (!editing && text.trim() !== "") {
    return (
      <div
        className="doc-edit"
        role="button"
        tabIndex={0}
        aria-label={`Edit ${def.name}`}
        onClick={() => setEditing(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setEditing(true);
          }
        }}
      >
        <RichText text={text} placeholder={placeholder} lineExtra={lineExtra} />
      </div>
    );
  }

  return (
    <textarea
      ref={ref}
      className="textarea seamless"
      rows={2}
      value={text}
      autoFocus={editing}
      placeholder={placeholder}
      aria-label={def.name}
      onFocus={onFocusEditor}
      onBlur={() => setEditing(false)}
      onChange={(e) => onChange({ ...section, text: e.target.value })}
    />
  );
}

function ChoiceField({ def, section, readOnly, onChange }: FieldProps) {
  const multi = def.field_type === "multi_choice";
  const meta = section.field_specific_metadata;
  const selected: string[] = multi
    ? (metaValue<string[]>(meta, "selected") ?? [])
    : ([metaValue<string>(meta, "selected")].filter(Boolean) as string[]);

  const pick = (value: string) => {
    let nextSel: string[];
    if (multi) {
      nextSel = selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value];
    } else {
      nextSel = selected[0] === value ? [] : [value];
    }
    const label = (v: string) => def.options?.find((o) => o.value === v)?.label ?? v;
    onChange({
      ...section,
      text: nextSel.map(label).join(", "),
      field_specific_metadata: manualMeta(nextSel.length === 0 ? null : { selected: multi ? nextSel : nextSel[0] }),
    });
  };

  return (
    <div className="seg wrap" role="group" aria-label={def.name}>
      {def.options?.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className="seg-opt"
          aria-pressed={selected.includes(opt.value)}
          disabled={readOnly}
          onClick={() => pick(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function DateField({ def, section, readOnly, onChange }: FieldProps) {
  const meta = section.field_specific_metadata;
  const date = metaValue<string>(meta, "date") ?? "";
  const withNote = def.field_type === "date_with_note";

  return (
    <div className="inline-row">
      <input
        className="input date-input"
        type="date"
        value={date}
        disabled={readOnly}
        aria-label={def.name}
        onChange={(e) => {
          const d = e.target.value;
          onChange({
            ...section,
            text: withNote ? section.text : d,
            field_specific_metadata: manualMeta(d ? { date: d } : null),
          });
        }}
      />
      {withNote && (
        <input
          className="input"
          type="text"
          placeholder="Note…"
          style={{ flex: 1, minWidth: 200 }}
          value={section.text ?? ""}
          disabled={readOnly}
          aria-label={`${def.name} note`}
          onChange={(e) => onChange({ ...section, text: e.target.value })}
        />
      )}
    </div>
  );
}

function NumericField({ def, section, readOnly, onChange }: FieldProps) {
  const meta = section.field_specific_metadata;
  const value = metaValue<number>(meta, "value");
  const unit = metaValue<string>(meta, "unit") ?? "";

  const update = (v: number | undefined, u: string) => {
    const has = v !== undefined && !Number.isNaN(v) && u.trim() !== "";
    onChange({
      ...section,
      text: has ? `${v} ${u.trim()}` : "",
      field_specific_metadata: manualMeta(has ? { value: v, unit: u.trim() } : null),
    });
  };

  return (
    <div className="inline-row">
      <input
        className="input num mono"
        type="number"
        value={value ?? ""}
        placeholder="Value"
        disabled={readOnly}
        aria-label={`${def.name} value`}
        onChange={(e) => update(e.target.value === "" ? undefined : Number(e.target.value), unit)}
      />
      <input
        className="input unit"
        type="text"
        value={unit}
        placeholder="Unit"
        disabled={readOnly}
        aria-label={`${def.name} unit`}
        onChange={(e) => update(value, e.target.value)}
      />
    </div>
  );
}

function SectionField(props: FieldProps) {
  switch (props.def.field_type) {
    case "choice":
    case "multi_choice":
      return <ChoiceField {...props} />;
    case "date":
    case "date_with_note":
      return <DateField {...props} />;
    case "numeric_with_unit":
      return <NumericField {...props} />;
    default:
      return <FreeTextField {...props} />;
  }
}

// ── transcript ────────────────────────────────────────────────────────

const UNKNOWN_SPEAKER = "Unknown speaker";

/** What a turn's speaker is called right now (people's names win over defaults). */
function turnName(turn: TranscriptTurn, names: Record<string, string>): string {
  if (!turn.speaker) return UNKNOWN_SPEAKER;
  return names[turn.speaker] ?? turn.name ?? defaultSpeakerName(turn.speaker);
}

/** Only the names people gave — what the job stores; defaults are implied. */
function customNames(names: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [label, name] of Object.entries(names)) {
    if (name && name !== defaultSpeakerName(label)) out[label] = name;
  }
  return out;
}

/**
 * Rewrite a speaker's name at the start of turns in note text:
 * "Speaker 2: …" → "Olena: …". The from-transcript note puts the name at
 * the start of a turn's first line, so only line-leading matches change.
 */
export function renameSpeakerInText(text: string, from: string, to: string): string {
  const escaped = from.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return text.replace(new RegExp(`(^|\\n)${escaped}: `, "g"), `$1${to}: `);
}

/**
 * The transcript as the from-transcript note writes it (note-service
 * `_turns_text`): a turn per block, the name at the start of its first
 * line. Used to tell whether the note's transcript section still says what
 * the job said — i.e. nobody has edited it.
 */
export function turnsToNoteText(turns: TranscriptTurn[], names: Record<string, string>): string {
  const diarized = turns.some((t) => t.speaker);
  return turns
    .flatMap((t) => {
      const paragraphs = t.paragraphs.map((p) => p.trim()).filter(Boolean);
      if (paragraphs.length === 0) return [];
      if (diarized) paragraphs[0] = `${turnName(t, names)}: ${paragraphs[0]}`;
      return [paragraphs.join("\n")];
    })
    .join("\n\n");
}

/** A speaker re-run (or its undo) landed: the transcript text before and after. */
export interface SpeakersRelabelled {
  kind: "rerun" | "undo";
  before: string;
  after: string;
}

interface TranscriptViewProps {
  jobId: string;
  /** A speaker was renamed on the job — the note body may want to follow. */
  onSpeakerRenamed?: (from: string, to: string) => void;
  /** A speaker was merged into another (display names) — the note body follows. */
  onSpeakersMerged?: (from: string, to: string) => void;
  /** The last merge was undone — the note body goes back if it was not edited since. */
  onSpeakerMergeUndone?: () => void;
  /** Speakers were re-labelled or the re-run undone — the note may want to follow. */
  onSpeakersRelabelled?: (change: SpeakersRelabelled) => void;
  /** Shown instead of the error when the job cannot be read (the note's own text). */
  fallback?: ReactNode;
  /** Q3: open at this moment (ms) — a "Not included" range was clicked.
   *  `seekKey` changes on every click, so the same range can be opened twice. */
  seekMs?: number | null;
  seekKey?: number;
}

/**
 * The transcript as it stands in the note text, for a note without a
 * readable recording job. Speaker names are still editable: a rename
 * rewrites every turn of that speaker in the note, which autosaves.
 */
function TextTranscriptView({
  texts,
  editable,
  onRename,
}: {
  texts: string[];
  editable: boolean;
  onRename: (from: string, to: string) => void;
}) {
  const [editing, setEditing] = useState<{ name: string; value: string } | null>(null);
  const blocks = useMemo(() => texts.flatMap((t) => parseRichText(t)), [texts]);
  const speakers = useMemo(
    () => new Set(blocks.flatMap((b) => (b.kind === "para" && b.speaker ? [b.speaker] : []))),
    [blocks],
  );

  const commit = () => {
    if (!editing) return;
    const { name, value } = editing;
    setEditing(null);
    const to = value.trim().split(/\s+/).join(" ").slice(0, 80);
    if (to && to !== name) onRename(name, to);
  };

  return (
    <div className="transcript">
      <div className="transcript-bar">
        <span className="help">
          {speakers.size === 0
            ? "Speakers were not told apart in this recording."
            : `${speakers.size === 1 ? "1 speaker" : `${speakers.size} speakers`}${editable ? " · click a name to rename" : ""}`}
        </span>
      </div>
      {blocks.map((block, i) => {
        if (block.kind !== "para") return null;
        const text = block.spans.map((s) => s.text).join("");
        if (!block.speaker) {
          return (
            <p key={i} className="turn-text" style={{ gridColumn: "1 / -1" }}>
              {text}
            </p>
          );
        }
        const name = block.speaker;
        const isEditing = editing !== null && editing.name === name;
        return (
          <div key={i} className="turn">
            <span className="speaker-avatar" style={{ "--tint": speakerTint(name) } as React.CSSProperties} aria-hidden="true">
              {speakerInitials(name)}
            </span>
            <div className="turn-h">
              {isEditing ? (
                <input
                  className="input speaker-input"
                  aria-label="Speaker name"
                  autoFocus
                  value={editing.value}
                  maxLength={80}
                  onChange={(e) => setEditing({ name, value: e.target.value })}
                  onBlur={commit}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commit();
                    if (e.key === "Escape") setEditing(null);
                  }}
                />
              ) : editable ? (
                <button type="button" className="turn-speaker" title="Rename this speaker" onClick={() => setEditing({ name, value: name })}>
                  {name}
                </button>
              ) : (
                <span className="turn-speaker">{name}</span>
              )}
            </div>
            <p className="turn-text">{text}</p>
          </div>
        );
      })}
    </div>
  );
}

/** "1 turn" / "3 turns". */
function turnsLabel(n: number): string {
  return n === 1 ? "1 turn" : `${n} turns`;
}

const UNCERTAIN_COPY = "People talked over each other here.";
const STALE_COPY = "Speakers were updated elsewhere.";

/** Where a turn can go: a roster label, a speaker the diarizer missed, or nobody. */
type MoveTarget = string | "new" | null;

/** How long a turn stays highlighted after a suggestion's quote is clicked. */
const HIGHLIGHT_MS = 2000;

/** The last speaker change that can still be undone. */
type UndoableEdit =
  | { editId: string; kind: "merge"; into: string }
  | { editId: string; kind: "reassign"; message: string }
  /** An accepted name suggestion: undo PUTs the names as they were. */
  | {
      kind: "names";
      label: string;
      prev: Record<string, string>;
      prevSource: SpeakerNameSource | undefined;
      from: string;
      to: string;
      message: string;
    };

function suggestionKey(s: NameSuggestion): string {
  return `${s.label}\u0000${s.name}`;
}

/** The turn a suggestion's quote sits in (by its first segment), or -1. */
export function turnOfSuggestion(turns: TranscriptTurn[], s: NameSuggestion): number {
  const first = s.segment_indices[0];
  if (first === undefined) return -1;
  return turns.findIndex((t) => t.segment_indices?.includes(first) ?? false);
}

/**
 * A polite live region for what just happened to the speakers ("Merged",
 * "Moved 3 turns", "Re-labelling finished"). Each message is a fresh node,
 * so saying the same thing twice is still announced.
 */
function useAnnouncer() {
  const [message, setMessage] = useState<{ text: string; n: number } | null>(null);
  const announce = useCallback((text: string) => setMessage((m) => ({ text, n: (m?.n ?? 0) + 1 })), []);
  const region = (
    <div className="sr-only" role="status" aria-live="polite" aria-label={copyText("announcementsRegion")}>
      {message && <span key={message.n}>{message.text}</span>}
    </div>
  );
  return { announce, region };
}

/**
 * The rename field for a speaker, with the meeting's invitees under it —
 * picking one saves straight away; typing still works.
 */
function SpeakerNameInput({
  value,
  options,
  onChange,
  onCommit,
  onPick,
  onCancel,
}: {
  value: string;
  options: string[];
  onChange: (value: string) => void;
  onCommit: () => void;
  onPick: (name: string) => void;
  onCancel: () => void;
}) {
  const host = useRef<HTMLSpanElement>(null);
  const focusOption = (i: number) => {
    const opts = host.current?.querySelectorAll<HTMLButtonElement>(".speaker-pick");
    if (!opts || opts.length === 0) return;
    opts[Math.max(0, Math.min(i, opts.length - 1))]?.focus();
  };
  return (
    <span
      className="dropdown-host speaker-name-edit"
      ref={host}
      onBlur={(e) => {
        // Moving into the list is not leaving the field.
        if (!host.current?.contains(e.relatedTarget as Node | null)) onCommit();
      }}
    >
      <input
        className="input speaker-input"
        aria-label="Speaker name"
        autoFocus
        value={value}
        maxLength={80}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onCommit();
          if (e.key === "Escape") onCancel();
          if (e.key === "ArrowDown" && options.length > 0) {
            e.preventDefault();
            focusOption(0);
          }
        }}
      />
      {options.length > 0 && (
        <div className="dropdown left speaker-picklist" role="group" aria-label="Invited people">
          {options.map((name, i) => (
            <button
              key={name}
              type="button"
              className="anchored-menu-item speaker-pick"
              tabIndex={-1}
              // Keep the input focused: a pick is not a blur-to-commit.
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => onPick(name)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  focusOption(i + 1);
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  if (i === 0) host.current?.querySelector<HTMLInputElement>("input")?.focus();
                  else focusOption(i - 1);
                } else if (e.key === "Escape") onCancel();
              }}
            >
              <span className="speaker-avatar sm" style={{ "--tint": speakerTint(name) } as React.CSSProperties} aria-hidden="true">
                {speakerInitials(name)}
              </span>
              <span className="anchored-menu-label">{name}</span>
            </button>
          ))}
        </div>
      )}
    </span>
  );
}

export function TranscriptView({
  jobId,
  onSpeakerRenamed,
  onSpeakersMerged,
  onSpeakerMergeUndone,
  onSpeakersRelabelled,
  fallback,
  seekMs,
  seekKey,
}: TranscriptViewProps) {
  const toast = useToast();
  const online = useOnline();
  const [result, setResult] = useState<TranscriptResult | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState<{ label: string; value: string; initial: string; turn: number } | null>(null);
  const [saving, setSaving] = useState(false);
  const [undo, setUndo] = useState<UndoableEdit | null>(null);
  // Sprint 32: suggestions turned down in this view (the server forgets them too).
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(() => new Set());
  const [highlight, setHighlight] = useState<number | null>(null);
  const { announce, region } = useAnnouncer();
  // Sprint 30: turns picked for one "Move N turns to" action, by position.
  const [selected, setSelected] = useState<ReadonlySet<number>>(() => new Set());
  const [focusTurn, setFocusTurn] = useState(0);
  const [relabelRunning, setRelabelRunning] = useState(false);
  const turnRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    if (!undo) return;
    const t = window.setTimeout(() => setUndo(null), 10_000);
    return () => window.clearTimeout(t);
  }, [undo]);

  useEffect(() => {
    if (highlight === null) return;
    const t = window.setTimeout(() => setHighlight(null), HIGHLIGHT_MS);
    return () => window.clearTimeout(t);
  }, [highlight]);

  const load = (r: TranscriptResult) => {
    setResult(r);
    setNames(r.speaker_names ?? {});
    // Positions mean other turns after a reload.
    setSelected(new Set());
  };

  const reload = async () => {
    load(await getResult(jobId));
  };

  // A re-run replaces the labelling (and the merges on it): reload, and
  // hand the note both versions of the text so it can offer to follow.
  const relabelled = async (kind: "rerun" | "undo") => {
    const before = result ? turnsToNoteText(result.turns ?? [], names) : null;
    const r = await getResult(jobId);
    load(r);
    setUndo(null);
    if (before !== null) {
      onSpeakersRelabelled?.({ kind, before, after: turnsToNoteText(r.turns ?? [], r.speaker_names ?? {}) });
    }
  };

  const merge = async (from: string, into: string) => {
    if (saving) return;
    const fromName = names[from] ?? defaultSpeakerName(from);
    setSaving(true);
    try {
      const res = await mergeSpeakers(jobId, from, into);
      // Optimistic: roster and talk share from the response, turns on reload.
      setResult((r) => (r ? { ...r, speakers: res.speakers, speaker_stats: res.speaker_stats } : r));
      setNames(res.speaker_names);
      setUndo({ editId: res.edit_id, kind: "merge", into });
      announce(copyText("announceMerged"));
      onSpeakersMerged?.(fromName, res.speaker_names[into] ?? defaultSpeakerName(into));
      await reload();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  /**
   * Move turns to another speaker — one call however many turns, their
   * segment indices concatenated. The turns change on screen first; the
   * reload after the call is the truth (a "new" speaker's label only
   * exists once the server made it).
   */
  const move = async (positions: number[], to: MoveTarget) => {
    if (!result || saving || typeof result.result_rev !== "number") return;
    const all = result.turns ?? [];
    const order = [...positions].sort((a, b) => a - b);
    const picked = order.map((i) => all[i]).filter((t): t is TranscriptTurn => t !== undefined);
    const segmentIndices = segmentIndicesOf(picked);
    if (segmentIndices.length === 0) return;
    const prev = result;
    const prevNames = names;
    const before = turnsToNoteText(all, names);
    const moving = new Set(order);
    if (to !== "new") {
      setResult({
        ...prev,
        turns: all.map((t, i) =>
          moving.has(i)
            ? { ...t, speaker: to, name: to ? (names[to] ?? defaultSpeakerName(to)) : null, uncertain: false }
            : t,
        ),
      });
    }
    setSelected(new Set());
    setSaving(true);
    try {
      const res = await reassignTurns(jobId, { resultRev: prev.result_rev!, segmentIndices, to });
      const label = to === "new" ? res.created_label : to;
      const target = label ? (res.speaker_names[label] ?? defaultSpeakerName(label)) : UNKNOWN_SPEAKER;
      setNames(res.speaker_names);
      setUndo({ editId: res.edit_id, kind: "reassign", message: `Moved ${turnsLabel(picked.length)} to ${target}` });
      announce(movedAnnouncement(picked.length));
      try {
        const r = await getResult(jobId);
        load(r);
        onSpeakersRelabelled?.({ kind: "rerun", before, after: turnsToNoteText(r.turns ?? [], r.speaker_names ?? {}) });
      } catch (err) {
        toast.error(errorMessage(err));
      }
    } catch (err) {
      if (err instanceof ApiError && err.code === "stale_result_rev") {
        // Someone (or another device) edited the speakers since this
        // view loaded: show theirs, and say so, rather than guess.
        try {
          await reload();
        } catch {
          setResult(prev);
          setNames(prevNames);
        }
        toast.info(STALE_COPY);
      } else {
        setResult(prev);
        setNames(prevNames);
        toast.error(messageFor(err));
      }
    } finally {
      setSaving(false);
    }
  };

  const undoEdit = async () => {
    if (!undo || saving) return;
    const edit = undo;
    const before = result ? turnsToNoteText(result.turns ?? [], names) : null;
    setSaving(true);
    try {
      if (edit.kind === "names") {
        const res = await setSpeakerNames(jobId, edit.prev);
        setUndo(null);
        const merged: Record<string, string> = {};
        for (const l of result?.speakers ?? []) merged[l] = res.speaker_names[l] ?? defaultSpeakerName(l);
        setNames(merged);
        setResult((r) => {
          if (!r) return r;
          const sources = { ...(r.speaker_name_sources ?? {}) };
          if (edit.prevSource === undefined) delete sources[edit.label];
          else sources[edit.label] = edit.prevSource;
          return { ...r, speaker_name_sources: sources };
        });
        onSpeakerRenamed?.(edit.to, merged[edit.label] ?? edit.from);
        announce(copyText("announceUndone"));
        return;
      }
      await undoSpeakerEdit(jobId, edit.editId);
      setUndo(null);
      if (edit.kind === "merge") {
        onSpeakerMergeUndone?.();
        await reload();
      } else {
        const r = await getResult(jobId);
        load(r);
        if (before !== null) {
          onSpeakersRelabelled?.({ kind: "undo", before, after: turnsToNoteText(r.turns ?? [], r.speaker_names ?? {}) });
        }
      }
    } catch (err) {
      toast.error(messageFor(err));
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    getResult(jobId)
      .then((r) => {
        if (cancelled) return;
        setResult(r);
        setNames(r.speaker_names ?? {});
      })
      .catch((err) => !cancelled && setError(errorMessage(err)));
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const turns = result?.turns ?? [];
  const speakerCount = useMemo(() => new Set(turns.map((t) => t.speaker).filter(Boolean)).size, [turns]);
  const diarized = speakerCount > 0;
  const roster = result?.speakers ?? [];
  // Moving turns needs the server's revision to guard against a stale
  // view, a connection, and no re-label in flight (it replaces the labels).
  const canMove =
    diarized && roster.length > 0 && online && !relabelRunning && typeof result?.result_rev === "number";
  const moveLocked = !canMove || saving;

  const copy = async () => {
    const text = turns
      .map((t) => {
        const body = t.paragraphs.join("\n");
        return diarized ? `${turnName(t, names)}: ${body}` : body;
      })
      .join("\n\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Couldn't copy — your browser blocked clipboard access.");
    }
  };

  const startRename = (label: string, turn: number) => {
    const current = names[label] ?? defaultSpeakerName(label);
    setEditing({ label, value: current, initial: current, turn });
  };

  const commitRename = async (picked?: string) => {
    if (!editing || saving) return;
    const { label } = editing;
    const value = picked ?? editing.value;
    const from = names[label] ?? defaultSpeakerName(label);
    const to = value.trim() || defaultSpeakerName(label);
    setEditing(null);
    if (to === from) return;
    const next = customNames(names);
    const cleared = to === defaultSpeakerName(label);
    if (cleared) delete next[label];
    else next[label] = to;
    const sources: Record<string, NameSource> | undefined = cleared
      ? undefined
      : { [label]: picked !== undefined ? "picklist" : "typed" };
    setSaving(true);
    try {
      const res = await setSpeakerNames(jobId, next, sources);
      const merged: Record<string, string> = {};
      for (const l of result?.speakers ?? []) merged[l] = res.speaker_names[l] ?? defaultSpeakerName(l);
      setNames(merged);
      // An edited name is the person's own now: the "suggested" marker goes.
      const source: SpeakerNameSource = sources?.[label] ?? "cleared";
      setResult((r) => (r ? { ...r, speaker_name_sources: { ...(r.speaker_name_sources ?? {}), [label]: source } } : r));
      onSpeakerRenamed?.(from, merged[label] ?? to);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  /** A microphone-given name was removed from its roster chip (Sprint 31). */
  const nameCleared = (label: string, speakerNames: Record<string, string>) => {
    const from = names[label] ?? defaultSpeakerName(label);
    const merged: Record<string, string> = {};
    for (const l of result?.speakers ?? []) merged[l] = speakerNames[l] ?? defaultSpeakerName(l);
    setNames(merged);
    setResult((r) =>
      r ? { ...r, speaker_name_sources: { ...(r.speaker_name_sources ?? {}), [label]: "cleared" } } : r,
    );
    onSpeakerRenamed?.(from, merged[label] ?? defaultSpeakerName(label));
  };

  // ── Sprint 32: name suggestions ──
  /** Suggestions still worth asking about: a live label nobody has named, not turned down. */
  const openSuggestions = (result?.name_suggestions ?? []).filter((sg) => {
    if (!roster.includes(sg.label) || dismissed.has(suggestionKey(sg))) return false;
    const current = names[sg.label];
    return current === undefined || current === defaultSpeakerName(sg.label);
  });

  const acceptSuggestion = async (sg: NameSuggestion) => {
    if (saving) return;
    const label = sg.label;
    const from = names[label] ?? defaultSpeakerName(label);
    const prev = customNames(names);
    const prevSource = result?.speaker_name_sources?.[label];
    setSaving(true);
    try {
      const res = await setSpeakerNames(jobId, { ...prev, [label]: sg.name }, { [label]: "suggestion" });
      const merged: Record<string, string> = {};
      for (const l of result?.speakers ?? []) merged[l] = res.speaker_names[l] ?? defaultSpeakerName(l);
      setNames(merged);
      setResult((r) =>
        r ? { ...r, speaker_name_sources: { ...(r.speaker_name_sources ?? {}), [label]: "suggestion" } } : r,
      );
      const to = merged[label] ?? sg.name;
      setUndo({
        kind: "names",
        label,
        prev,
        prevSource,
        from,
        to,
        message: copyText("acceptedUndo", { speaker: from, name: to }),
      });
      announce(copyText("announceNamed", { name: to }));
      onSpeakerRenamed?.(from, to);
    } catch (err) {
      toast.error(copyText("acceptFailed", { speaker: from, reason: messageFor(err) }));
    } finally {
      setSaving(false);
    }
  };

  const dismissSuggestion = async (sg: NameSuggestion) => {
    const key = suggestionKey(sg);
    setDismissed((d) => new Set(d).add(key));
    try {
      await dismissNameSuggestion(jobId, sg.label, sg.name);
    } catch (err) {
      setDismissed((d) => {
        const next = new Set(d);
        next.delete(key);
        return next;
      });
      toast.error(copyText("dismissFailed", { reason: messageFor(err) }));
    }
  };

  // Q3: a "Not included" range was clicked on the Notes tab — scroll to
  // the turn that holds that moment and light it up, as for a suggestion.
  useEffect(() => {
    if (seekMs == null || turns.length === 0) return;
    let i = turns.findIndex((t) => t.start_ms <= seekMs && seekMs < t.end_ms);
    if (i < 0) i = turns.reduce((best, t, k) => (t.start_ms <= seekMs ? k : best), 0);
    const el = turnRefs.current[i];
    if (!el) return;
    setFocusTurn(i);
    el.scrollIntoView?.({ block: "center", behavior: "smooth" });
    setHighlight(i);
    // Re-run on every click (seekKey), and once the turns have loaded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seekMs, seekKey, turns.length]);

  /** Scroll to the turn a suggestion quotes, focus it, and light it up for a moment. */
  const showSuggestion = (sg: NameSuggestion) => {
    const i = turnOfSuggestion(turns, sg);
    const el = i >= 0 ? turnRefs.current[i] : null;
    if (!el) return;
    setFocusTurn(i);
    el.scrollIntoView?.({ block: "center", behavior: "smooth" });
    el.focus({ preventScroll: true });
    setHighlight(i);
  };

  /** The "move to" choices for turns currently spoken by `from`. */
  const moveItems = (positions: number[], from: ReadonlySet<string | null>): MenuItem[] => {
    const only = from.size === 1 ? [...from][0] : undefined;
    const items: MenuItem[] = roster
      .filter((l) => !(from.size === 1 && l === only))
      .map((l) => {
        const n = names[l] ?? defaultSpeakerName(l);
        return {
          label: n,
          icon: (
            <span className="speaker-avatar sm" style={{ "--tint": speakerTint(n) } as React.CSSProperties} aria-hidden="true">
              {speakerInitials(n)}
            </span>
          ),
          onClick: () => void move(positions, l),
          disabled: moveLocked,
        };
      });
    items.push({ label: "New speaker", onClick: () => void move(positions, "new"), disabled: moveLocked, sep: items.length > 0 });
    if (!(from.size === 1 && only === null)) {
      items.push({ label: "Unknown", onClick: () => void move(positions, null), disabled: moveLocked });
    }
    return items;
  };

  const toggle = (i: number) => {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  };

  const onTurnKey = (e: React.KeyboardEvent<HTMLDivElement>, i: number) => {
    if (e.target !== e.currentTarget) return; // typing a name, or inside a menu
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const next = Math.max(0, Math.min(turns.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)));
      setFocusTurn(next);
      turnRefs.current[next]?.focus();
    } else if (e.key === "Escape" && selected.size > 0) {
      setSelected(new Set());
    } else if (/^[1-8]$/.test(e.key) && !e.altKey && !e.ctrlKey && !e.metaKey) {
      const label = roster[Number(e.key) - 1];
      if (!label || moveLocked || label === turns[i]?.speaker) return;
      e.preventDefault();
      void move([i], label);
    }
  };

  if (error) {
    if (fallback) return <>{fallback}</>;
    return (
      <div className="banner banner-danger" role="alert">
        <AlertIcon size={15} />
        <span className="grow">{error}</span>
      </div>
    );
  }
  if (!result) {
    return (
      <div aria-busy="true" aria-label="Loading transcript" className="transcript">
        <Skeleton style={{ height: 56 }} />
        <Skeleton style={{ height: 56 }} />
        <Skeleton style={{ height: 56 }} />
      </div>
    );
  }
  const selection = [...selected].sort((a, b) => a - b);
  const hasRoster = diarized && (result.speakers?.length ?? 0) > 0;
  const moveHelp = !online ? "Needs a connection" : relabelRunning ? "Wait for the re-label to finish" : undefined;
  return (
    <div className={`transcript ${selected.size > 0 ? "selecting" : ""}`}>
      {region}
      <div className="transcript-bar">
        {(hasRoster || result.relabel_available === true) && (
          <SpeakerRoster
            jobId={jobId}
            speakers={diarized ? (result.speakers ?? []) : []}
            names={names}
            stats={result.speaker_stats ?? []}
            busy={saving}
            undo={
              undo
                ? undo.kind === "merge"
                  ? { into: undo.into, onUndo: () => void undoEdit() }
                  : { message: undo.message, onUndo: () => void undoEdit() }
                : null
            }
            countConfidence={result.count_confidence ?? null}
            speakersHint={result.speakers_hint ?? null}
            mergeCount={result.edits?.length ?? 0}
            sides={result.speaker_sides ?? {}}
            nameSources={result.speaker_name_sources ?? {}}
            suggestions={openSuggestions}
            relabelAvailable={result.relabel_available === true}
            onAcceptSuggestion={(sg) => void acceptSuggestion(sg)}
            onDismissSuggestion={(sg) => void dismissSuggestion(sg)}
            onShowSuggestion={showSuggestion}
            onNameCleared={nameCleared}
            onRename={(label) => startRename(label, turns.findIndex((t) => t.speaker === label))}
            onMerge={(from, into) => void merge(from, into)}
            onRelabelled={async (kind) => {
              await relabelled(kind);
              announce(copyText(kind === "rerun" ? "announceRelabelled" : "announceRelabelUndone"));
            }}
            onRelabelRunning={setRelabelRunning}
            onReset={() => relabelled("rerun")}
          />
        )}
        {!hasRoster && (
          <span className="help">
            {turns.length === 0
              ? "Nothing was said."
              : !diarized
                ? "Speakers were not told apart in this recording."
                : `${speakerCount === 1 ? "1 speaker" : `${speakerCount} speakers`} · click a name to rename`}
          </span>
        )}
        <span className="grow" />
        <button className="btn ghost sm" onClick={() => void copy()} disabled={turns.length === 0}>
          {copied ? <CheckIcon size={14} /> : <CopyIcon size={14} />} {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {selection.length > 0 && (
        <div className="turn-actions" role="toolbar" aria-label="Selected turns">
          <span className="grow">{turnsLabel(selection.length)} selected</span>
          <Menu
            anchored
            label={`Move ${turnsLabel(selection.length)} to`}
            triggerClassName="btn sm"
            trigger={<>Move {turnsLabel(selection.length)} to ▸</>}
            disabled={moveLocked}
            items={moveItems(selection, new Set(selection.map((i) => turns[i]?.speaker ?? null)))}
          />
          <button className="btn ghost sm" onClick={() => setSelected(new Set())}>
            Clear
          </button>
        </div>
      )}
      {turns.map((t, i) => {
        const name = turnName(t, names);
        const isEditing = editing !== null && t.speaker !== null && editing.label === t.speaker && editing.turn === i;
        const isSelected = selected.has(i);
        const here = openSuggestions.filter((sg) => turnOfSuggestion(turns, sg) === i);
        return (
          <div
            key={i}
            ref={(el) => {
              turnRefs.current[i] = el;
            }}
            data-turn-index={i}
            className={`turn ${isSelected ? "selected" : ""} ${highlight === i ? "highlighted" : ""}`}
            tabIndex={diarized ? (i === focusTurn ? 0 : -1) : undefined}
            role={diarized ? "group" : undefined}
            aria-label={diarized ? `${name}, ${formatElapsed(t.start_ms)}` : undefined}
            onFocus={(e) => e.target === e.currentTarget && setFocusTurn(i)}
            onKeyDown={diarized ? (e) => onTurnKey(e, i) : undefined}
            onClickCapture={(e) => {
              // Shift-click anywhere on a turn picks it for a group move.
              if (!e.shiftKey || !canMove) return;
              e.preventDefault();
              e.stopPropagation();
              toggle(i);
            }}
          >
            {diarized && (
              <span className="turn-avatar-host" style={{ "--tint": speakerTint(name) } as React.CSSProperties}>
                <Menu
                  anchored
                  label={`${name} — move this turn`}
                  triggerClassName="speaker-avatar turn-avatar"
                  disabled={moveLocked}
                  items={moveItems([i], new Set([t.speaker]))}
                  trigger={speakerInitials(name)}
                />
                {t.uncertain && (
                  <span className="turn-uncertain" role="img" aria-label={UNCERTAIN_COPY} title={UNCERTAIN_COPY}>
                    ?
                  </span>
                )}
              </span>
            )}
            <div className="turn-h">
              {diarized &&
                (isEditing ? (
                  <SpeakerNameInput
                    value={editing.value}
                    options={pickableNames(result.name_candidates, names, editing.label).filter(
                      (n) =>
                        editing.value === editing.initial ||
                        n.toLocaleLowerCase().includes(editing.value.trim().toLocaleLowerCase()),
                    )}
                    onChange={(value) => setEditing({ ...editing, value })}
                    onCommit={() => void commitRename()}
                    onPick={(n) => void commitRename(n)}
                    onCancel={() => setEditing(null)}
                  />
                ) : t.speaker ? (
                  <button
                    type="button"
                    className="turn-speaker"
                    title="Rename this speaker"
                    disabled={saving}
                    onClick={() => startRename(t.speaker!, i)}
                  >
                    {name}
                  </button>
                ) : (
                  <span className="turn-speaker unknown">{UNKNOWN_SPEAKER}</span>
                ))}
              <span className="turn-time mono">{formatElapsed(t.start_ms)}</span>
              {diarized && (
                <input
                  type="checkbox"
                  className="chk turn-select"
                  aria-label={`Select turn at ${formatElapsed(t.start_ms)}`}
                  title={moveHelp}
                  checked={isSelected}
                  disabled={!canMove}
                  onChange={() => toggle(i)}
                />
              )}
            </div>
            {t.paragraphs.map((p, j) => (
              <p key={j} className="turn-text">
                {p}
              </p>
            ))}
            {here.map((sg) => (
              <NameSuggestionChip
                key={suggestionKey(sg)}
                inline
                suggestion={sg}
                speakerName={names[sg.label] ?? defaultSpeakerName(sg.label)}
                disabled={saving || !online || relabelRunning}
                onAccept={(x) => void acceptSuggestion(x)}
                onDismiss={(x) => void dismissSuggestion(x)}
              />
            ))}
          </div>
        );
      })}
    </div>
  );
}

/**
 * The note's title. A textarea rather than an input, so a meeting's real
 * name — which is a sentence, not a label — wraps onto a second line
 * instead of scrolling out of sight. Return is not a line break here: a
 * title is one line of text however many rows it takes to show.
 */
function TitleField({
  value,
  disabled,
  onChange,
}: {
  value: string;
  disabled: boolean;
  onChange: (next: string) => void;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  return (
    <textarea
      ref={ref}
      className="title-input"
      rows={1}
      value={value}
      placeholder="Untitled note"
      aria-label="Note title"
      disabled={disabled}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.preventDefault();
      }}
      onChange={(e) => onChange(e.target.value.replace(/\n/g, " "))}
    />
  );
}

// ── meta row ──────────────────────────────────────────────────────────

/**
 * The "filed in" pill. A note already in a space links to it; one that
 * isn't opens the list of spaces so filing it is one click, not a trip
 * through the ⋯ menu. With no spaces yet there is nothing to offer, so
 * the pill stays out of the row entirely.
 */
function SpacePill({ noteId }: { noteId: string }) {
  const { spaces, spaceOf, file } = useSpaces();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss<HTMLDivElement>(open, close);
  const current = spaceOf[noteId];
  const space = spaces.find((sp) => sp.id === current);

  if (spaces.length === 0) return null;
  if (space) {
    return (
      <Link to={`/spaces/${space.id}`} className="doc-pill" title="Open this space">
        <FolderIcon size={13} />
        {space.name}
      </Link>
    );
  }
  return (
    <div className="dropdown-host" ref={ref}>
      <button
        type="button"
        className={`doc-pill ${open ? "on" : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <FolderPlusIcon size={13} />
        Add to space
      </button>
      {open && (
        <div className="dropdown left" role="menu" aria-label="Spaces">
          {spaces.map((sp) => (
            <button
              key={sp.id}
              type="button"
              className="anchored-menu-item"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                void file(noteId, sp.id);
              }}
            >
              <FolderIcon size={14} />
              <span className="anchored-menu-label">{sp.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── the page ──────────────────────────────────────────────────────────

// Sprint 36: "client" is what someone outside the workspace sees.
type Tab = "notes" | "transcript" | "responses" | "client";

export function NoteEditorPage() {
  const { noteId = "" } = useParams();
  const toast = useToast();
  const { identity } = useAuth();
  const navigate = useNavigate();
  const { spaces, spaceOf, file: fileInSpace, forgetNote } = useSpaces();

  const [note, setNote] = useState<NoteEnvelope | null>(null);
  const [sections, setSections] = useState<TemplateSection[] | null>(null);
  const [content, setContent] = useState<NoteContent | null>(null);
  /** The template's display name, for the meta row; null when it could not be read. */
  const [templateName, setTemplateName] = useState<string | null>(null);
  /** Q3: what the latest generation took the recording to be. */
  const [recordingType, setRecordingType] = useState<string | null>(null);
  /** Q3: a moment to open the transcript at ("Not included" link). */
  const [seek, setSeek] = useState<{ ms: number; key: number } | null>(null);

  const [version, setVersion] = useState(0);
  /** Q5: the evidence rows behind the generated lines, by line key. */
  const { rows: genRows, byKey: genByKey } = useGeneratedLines(noteId, version);
  /** Q5: how much of a generated note to show. A view, never an edit. */
  const [detail, setDetail] = useState<DetailLevel>(() => readDetail(noteId));
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [conflict, setConflict] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  /**
   * Set when this is not our note and nobody shared it with us — a
   * workspace admin opening a colleague's note. Every read is then sent
   * with this purpose (the server records it) and the page says so.
   */
  const [readPurpose, setReadPurpose] = useState<ReadPurpose | null>(null);

  const [params] = useSearchParams();
  // `?tab=responses` is the notification's deep link (Sprint 20).
  const [tab, setTab] = useState<Tab>(params.get("tab") === "responses" ? "responses" : "notes");
  const [items, setItems] = useState<ItemView[]>([]);
  const [responses, setResponses] = useState<ResponseView[]>([]);
  const [sourceJobId, setSourceJobId] = useState<string | null>(() => jobForNote(noteId));

  const [versions, setVersions] = useState<NoteVersionSummary[] | null>(null);
  const [showVersions, setShowVersions] = useState(false);
  const [viewing, setViewing] = useState<NoteVersionDetail | null>(null);

  const [confirmDelete, setConfirmDelete] = useState(false);
  const [showShare, setShowShare] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const saveTimer = useRef<number | null>(null);
  const latest = useRef<{ content: NoteContent; version: number } | null>(null);

  // Sprint 20: items are derived from the "Action items" section on
  // read; the tab shows whenever there is something to act on.
  const responseCount = responses.length;
  const hasResponsesTab = items.length > 0 || responses.length > 0;
  useEffect(() => {
    if (!note || note.status === "cancelled") {
      setItems([]);
      setResponses([]);
      return;
    }
    let live = true;
    Promise.all([getItems(noteId), getResponses(noteId)])
      .then(([i, r]) => {
        if (!live) return;
        setItems(i);
        setResponses(r);
      })
      .catch(() => {
        /* a reader without manage rights, or an old server: the tab simply stays hidden */
      });
    return () => {
      live = false;
    };
  }, [noteId, note?.status, note?.current_version_id]);

  // ── load ────────────────────────────────────────────────────────────

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      let env: NoteEnvelope;
      try {
        env = await getNote(noteId);
        setReadPurpose(null);
      } catch (err) {
        if (!needsReadPurpose(err)) throw err;
        // Not our note: read it as a reviewer, on the record.
        env = await getNote(noteId, "review");
        setReadPurpose("review");
      }
      setNote(env);
      if (env.source_job_id) setSourceJobId(env.source_job_id);
      setContent(env.content ?? null);
      setVersion(env.current_version_number);
      setSaveState("saved");
      setConflict(false);
      setViewing(null);
      if (env.content?.template_id) {
        try {
          const tpl = await getTemplate(env.content.template_id);
          setTemplateName(tpl.name);
          setSections([...tpl.schema_jsonb.sections].sort((a, b) => (a.order ?? 0) - (b.order ?? 0)));
        } catch {
          // Template unavailable (deprecated/permissions): fall back to the
          // envelope's section labels as plain free-text sections.
          setTemplateName(null);
          setSections(
            (env.section_labels ?? []).map((l) => ({
              id: l.section_key,
              name: l.name.en || l.name.uk || l.section_key,
            })),
          );
        }
      } else {
        setTemplateName(null);
        setSections([]);
      }
    } catch (err) {
      setLoadError(errorMessage(err));
    }
  }, [noteId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Which transcription (if any) this note came from — for the Transcript
  // tab. The envelope doesn't say, so ask the note service about the
  // recent jobs; the answer is cached per browser.
  useEffect(() => {
    if (sourceJobId) return;
    let cancelled = false;
    void (async () => {
      try {
        const jobs = await listJobs();
        const ids = jobs.filter((j) => j.status === "complete").map((j) => j.id);
        const links = await notesBySourceJob(ids);
        for (const l of links) rememberLink(l.asr_job_id, l.note_id);
        const mine = links.find((l) => l.note_id === noteId);
        if (mine && !cancelled) setSourceJobId(mine.asr_job_id);
      } catch {
        /* no transcript tab, then */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [noteId, sourceJobId]);

  // ── autosave ────────────────────────────────────────────────────────

  const flushSave = useCallback(async () => {
    const snap = latest.current;
    if (!snap) return;
    latest.current = null;
    setSaveState("saving");
    try {
      const res = await updateDraft(noteId, snap.content, snap.version);
      setVersion(res.version_number);
      setSaveState(latest.current ? "dirty" : "saved");
    } catch (err) {
      if (err instanceof ApiError && err.isConflict) {
        setConflict(true);
        setSaveState("error");
      } else {
        setSaveState("error");
        toast.error(errorMessage(err));
      }
    }
  }, [noteId, toast]);

  const scheduleSave = useCallback(
    (next: NoteContent, fromVersion: number) => {
      latest.current = { content: next, version: fromVersion };
      setSaveState("dirty");
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(() => void flushSave(), AUTOSAVE_MS);
    },
    [flushSave],
  );

  useEffect(
    () => () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
    },
    [],
  );

  // A note is a living document (ADR-0051): editable until cancelled.
  const isDraft = note !== null && note.status !== "cancelled";
  const editable = isDraft && !viewing;

  const onContentChange = (next: NoteContent) => {
    setContent(next);
    if (isDraft) scheduleSave(next, version);
  };

  // A speaker renamed in the transcript is renamed in the note too — the
  // note's turn lines start with the name. A cancelled note is a record;
  // its text stays, and only the transcript shows the new name.
  // Sprint 35: a name the author fixed is worth remembering — offered,
  // never taken. One term, one question.
  const [pendingTerm, setPendingTerm] = useState<PendingTerm | null>(null);
  const offerToRemember = (from: string, to: string) => {
    if (isWorthRemembering(from, to)) {
      setPendingTerm({ term: to.trim(), heardAs: heardAsOf(from) });
    }
  };

  const onSpeakerRenamed = (from: string, to: string) => {
    offerToRemember(from, to);
    if (!content || !isDraft) {
      toast.success(isDraft ? "Speaker renamed" : "Speaker renamed in the transcript");
      return;
    }
    const next: NoteContent = {
      ...content,
      sections: content.sections?.map((s) =>
        s.text ? { ...s, text: renameSpeakerInText(s.text, from, to) } : s,
      ),
    };
    if (JSON.stringify(next) !== JSON.stringify(content)) onContentChange(next);
    toast.success("Speaker renamed");
  };

  // A merge rewrites the note's turn lines like a rename. Undo puts the
  // text back only if nobody touched the note in between.
  const mergeRewrite = useRef<{ before: NoteContent; after: NoteContent } | null>(null);
  const onSpeakersMerged = (from: string, to: string) => {
    mergeRewrite.current = null;
    if (!content || !isDraft) return;
    const next: NoteContent = {
      ...content,
      sections: content.sections?.map((s) =>
        s.text ? { ...s, text: renameSpeakerInText(s.text, from, to) } : s,
      ),
    };
    if (JSON.stringify(next) === JSON.stringify(content)) return;
    mergeRewrite.current = { before: content, after: next };
    onContentChange(next);
  };
  const onSpeakerMergeUndone = () => {
    const rewrite = mergeRewrite.current;
    mergeRewrite.current = null;
    if (!rewrite) return;
    if (JSON.stringify(content) === JSON.stringify(rewrite.after)) onContentChange(rewrite.before);
    else toast.info("Note text was edited; speaker names in the note were not reverted.");
  };

  // A speaker re-run is bigger than a merge — turns can move between
  // people — so the note is not rewritten on its own. It is offered, and
  // done only while the transcript section still reads exactly as the old
  // labelling did (nobody edited it); undoing the re-run puts the section
  // back the way a merge undo does.
  const [relabelOffer, setRelabelOffer] = useState<{ before: string; after: string } | null>(null);
  const relabelRewrite = useRef<{ before: NoteContent; after: NoteContent } | null>(null);
  const onSpeakersRelabelled = ({ kind, before, after }: SpeakersRelabelled) => {
    setRelabelOffer(null);
    const rewrite = relabelRewrite.current;
    relabelRewrite.current = null;
    if (kind === "undo") {
      if (!rewrite) return;
      if (JSON.stringify(content) === JSON.stringify(rewrite.after)) onContentChange(rewrite.before);
      else toast.info("Note text was edited; speaker names in the note were not reverted.");
      return;
    }
    if (content && isDraft && before !== after) setRelabelOffer({ before, after });
  };
  const applyRelabel = () => {
    const offer = relabelOffer;
    setRelabelOffer(null);
    if (!offer || !content) return;
    let hit = false;
    const next: NoteContent = {
      ...content,
      sections: content.sections?.map((s) => {
        if (s.text?.trim() !== offer.before.trim()) return s;
        hit = true;
        return { ...s, text: offer.after };
      }),
    };
    if (!hit) {
      toast.info("The note's transcript was edited, so it was left as it is. The Transcript tab shows the new speakers.");
      return;
    }
    relabelRewrite.current = { before: content, after: next };
    onContentChange(next);
    toast.success("Speaker names updated in the note");
  };

  // ── actions ─────────────────────────────────────────────────────────

  const fileBase = () => safeFilename(shownContent?.title ?? "", note?.code ?? "note");

  const onPdf = async () => {
    try {
      saveBlob(await downloadPdf(noteId, readPurpose ? "export" : undefined), `${fileBase()}.pdf`);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const onMarkdown = () => {
    if (!shownContent || !sections) return;
    const md = noteToMarkdown({
      title: shownContent.title ?? "",
      code: note?.code ?? "",
      updatedAt: note?.updated_at,
      sections: noteBlocks(shownContent, sections, { editable: false }).map((block) => ({
        name: block.title ?? "",
        text: block.section.text ?? "",
      })),
    });
    saveBlob(new Blob([md], { type: "text/markdown;charset=utf-8" }), `${fileBase()}.md`);
  };

  const onDelete = async () => {
    setBusy(true);
    setActionError(null);
    try {
      await deleteNote(noteId);
      forgetNote(noteId);
      toast.success("Note deleted");
      navigate("/", { replace: true });
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const toggleVersions = async () => {
    const opening = !showVersions;
    setShowVersions(opening);
    setViewing(null);
    if (opening && versions === null) {
      try {
        setVersions(await listVersions(noteId, readPurpose ?? undefined));
      } catch (err) {
        toast.error(errorMessage(err));
        setVersions([]);
      }
    }
  };

  const openVersion = async (v: NoteVersionSummary) => {
    if (v.version_number === version && !viewing) return;
    try {
      setViewing(await getVersion(noteId, v.version_number, readPurpose ?? undefined));
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  // ── render ──────────────────────────────────────────────────────────

  const shownContent = viewing ? viewing.content : content;
  // A dialogue-shaped section is the raw transcript: it lives behind the
  // Transcript tab (read-only, speaker turns typeset), never in the notes.
  const transcriptDefs = (sections ?? []).filter(
    (def) => shownContent !== null && isTranscript(sectionOf(shownContent, def.id).text ?? ""),
  );
  const hasTranscript = sourceJobId !== null || transcriptDefs.length > 0;
  // What the content has, in its order. Structure follows content: no
  // template section is drawn for being in the template.
  const allBlocks = noteBlocks(shownContent, sections ?? [], { editable });
  // Q5: evidence and the detail toggle only for the note as it stands,
  // and only when the engine wrote it (it has rows).
  const generated = !viewing && genRows.length > 0;
  const blocks = generated && detail === "short" ? allBlocks.filter((b) => b.key === "gen:overview") : allBlocks;
  const lineExtra: LineExtra | undefined = generated
    ? (raw) => {
        const row = genByKey.get(lineKey(raw));
        return row ? <LineEvidence noteId={noteId} row={row} rowsByKey={genByKey} /> : null;
      }
    : undefined;
  const alsoSaid = generated && detail === "detailed" ? uncitedBySection(genRows, shownContent) : null;
  const saveLabel = useMemo(() => {
    switch (saveState) {
      case "saving":
        return "Saving…";
      case "dirty":
        return "Unsaved";
      case "error":
        return conflict ? "Out of date" : "Save failed";
      default:
        return "Saved";
    }
  }, [saveState, conflict]);

  if (loadError) {
    return (
      <div className="doc">
        <div className="banner banner-danger" role="alert">
          <AlertIcon size={15} />
          <span className="grow">{loadError}</span>
        </div>
        <div className="center-row">
          <button className="btn" onClick={() => void load()}>
            Try again
          </button>
          <Link to="/" className="btn ghost">
            Back to notes
          </Link>
        </div>
      </div>
    );
  }

  if (!note || !shownContent || sections === null) {
    return (
      <div className="doc" aria-busy="true" aria-label="Loading note">
        <Skeleton style={{ height: 32, width: "45%", marginBottom: 10 }} />
        <Skeleton style={{ height: 16, width: "30%", marginBottom: 28 }} />
        <Skeleton style={{ height: 80, marginBottom: 16 }} />
        <Skeleton style={{ height: 80 }} />
      </div>
    );
  }

  const menu: MenuItem[] = [
    { label: "Share…", icon: <ShareIcon size={14} />, onClick: () => setShowShare(true) },
    { label: "Download PDF", icon: <DownloadIcon size={14} />, sep: true, onClick: () => void onPdf() },
    { label: "Download Markdown", icon: <FileDownIcon size={14} />, onClick: onMarkdown },
    { label: showVersions ? "Hide history" : "History", icon: <HistoryIcon size={14} />, onClick: () => void toggleVersions() },
  ];
  if (!viewing && spaces.length > 0) {
    const current = spaceOf[noteId];
    spaces.forEach((sp, i) => {
      menu.push({
        label: current === sp.id ? `Remove from ${sp.name}` : `Move to ${sp.name}`,
        icon: <FolderIcon size={14} />,
        sep: i === 0,
        onClick: () => void fileInSpace(noteId, current === sp.id ? null : sp.id),
      });
    });
  }
  if (!viewing) {
    menu.push({
      label: "Delete note",
      icon: <TrashIcon size={14} />,
      sep: true,
      danger: true,
      disabled: busy,
      onClick: () => {
        setActionError(null);
        setConfirmDelete(true);
      },
    });
  }

  const authorName = note.primary_author_name?.trim() || "a colleague";

  return (
    <div className="doc-wrap">
      <div className="doc">
        {readPurpose && (
          <div className="banner banner-info" role="status">
            <UserIcon size={15} />
            <span className="grow">
              This is {authorName}&rsquo;s note. You can see it because you run this workspace,
              and this view is recorded.
            </span>
          </div>
        )}
        <div className="doc-bar">
          <Link to="/" className="tb-back" title="Back to notes" aria-label="Back to notes">
            <ArrowLeftIcon size={15} />
          </Link>
          {viewing ? (
            <>
              <StatusBadge status={`v${viewing.version_number}`} />
              <button className="btn sm" onClick={() => setViewing(null)}>
                Back to current
              </button>
            </>
          ) : (
            note.status === "cancelled" && <StatusBadge status={note.status} />
          )}
          <span className="grow" />
          {isDraft && !viewing && (
            <span className="save-status" data-state={saveState} role="status">
              <span className="dot" aria-hidden="true" />
              {saveLabel}
            </span>
          )}
          <Menu items={menu} />
        </div>

        <TitleField
          value={shownContent.title ?? ""}
          disabled={!editable}
          onChange={(title) => onContentChange({ ...shownContent, title })}
        />
        {/* The meta line is a row of pills, not a run of text: when it
            was taken, whose it is, what wrote it, where it is filed, what
            it is called. Only the space is a control — the rest are the
            facts you want at a glance without reading a sentence. */}
        <div className="doc-meta">
          <span className="doc-pill" title={`Created ${formatDateTime(note.created_at)}`}>
            <CalendarIcon size={13} />
            {formatDateTime(note.created_at)}
          </span>
          <span className="doc-pill" title={`Updated ${formatDateTime(note.updated_at)}`}>
            Updated {relativeTime(note.updated_at)}
          </span>
          <span className="doc-pill">
            <UserIcon size={13} />
            {readPurpose ? authorName : "Me"}
          </span>
          <DocTypePill templateName={templateName} recordingType={recordingType} />
          <SpacePill noteId={noteId} />
          <span className="doc-pill mono" title="This note's code">
            {note.code}
          </span>
        </div>

        {conflict && (
          <div className="banner banner-warn" role="alert">
            <AlertIcon size={15} />
            <span className="grow">Someone else saved a newer version of this note.</span>
            <button className="btn sm" onClick={() => void load()}>
              Reload latest
            </button>
          </div>
        )}

        {(hasTranscript || hasResponsesTab || isDraft) && (
          <div className="tabs doc-tabs" role="tablist">
            <button className={`tab ${tab === "notes" ? "on" : ""}`} role="tab" aria-selected={tab === "notes"} onClick={() => setTab("notes")}>
              Notes
            </button>
            {hasTranscript && (
              <button
                className={`tab ${tab === "transcript" ? "on" : ""}`}
                role="tab"
                aria-selected={tab === "transcript"}
                onClick={() => setTab("transcript")}
              >
                Transcript
              </button>
            )}
            {hasResponsesTab && (
              <button
                className={`tab ${tab === "responses" ? "on" : ""}`}
                role="tab"
                aria-selected={tab === "responses"}
                onClick={() => setTab("responses")}
              >
                Responses{responseCount > 0 && <span className="count">{responseCount}</span>}
              </button>
            )}
            {/* Before sending anything, see what they will actually get. */}
            <button
              className={`tab ${tab === "client" ? "on" : ""}`}
              role="tab"
              aria-selected={tab === "client"}
              onClick={() => setTab("client")}
            >
              Client version
            </button>
          </div>
        )}

        {tab === "client" ? (
          <ClientVersionPanel noteId={noteId} />
        ) : tab === "responses" && hasResponsesTab ? (
          <ResponsesPanel
            noteId={noteId}
            items={items}
            responses={responses}
            sections={[
              ...sections,
              ...blocks.filter((b) => !b.def && b.title).map((b) => ({ id: b.key, name: b.title ?? "" })),
            ]}
            onItems={setItems}
            onResponses={setResponses}
          />
        ) : tab === "transcript" && (sourceJobId || transcriptDefs.length > 0) ? (
          (() => {
            const textView =
              transcriptDefs.length > 0 ? (
                <TextTranscriptView
                  texts={transcriptDefs.map((def) => sectionOf(shownContent, def.id).text ?? "")}
                  editable={editable}
                  onRename={onSpeakerRenamed}
                />
              ) : undefined;
            return sourceJobId ? (
              <>
                <RememberTermPrompt
                  pending={pendingTerm}
                  onDone={() => setPendingTerm(null)}
                />
                {relabelOffer && (
                  <div className="banner banner-info note-relabel" role="note">
                    <span className="grow">Update speaker names in the note?</span>
                    <button className="btn sm" onClick={applyRelabel}>
                      Update note
                    </button>
                    <button className="btn ghost sm" onClick={() => setRelabelOffer(null)}>
                      Not now
                    </button>
                  </div>
                )}
                <TranscriptView
                  jobId={sourceJobId}
                  onSpeakerRenamed={onSpeakerRenamed}
                  onSpeakersMerged={onSpeakersMerged}
                  onSpeakerMergeUndone={onSpeakerMergeUndone}
                  onSpeakersRelabelled={onSpeakersRelabelled}
                  fallback={textView}
                  seekMs={seek?.ms ?? null}
                  seekKey={seek?.key}
                />
              </>
            ) : textView;
          })()
        ) : (
          <div className="doc-body">
            {/* Sprint 36: unfinished business from the last meeting in
                this series, above what was agreed in this one. */}
            {/* Sprint 33/37: what the engine is doing with this note, or
                why it is not. Never blocks the page — the note is the
                author's the whole time. */}
            <GenerationStatus
              noteId={noteId}
              canGenerate={editable && sourceJobId !== null}
              canRegenerate={editable}
              onFinished={load}
              onView={(view) => setRecordingType(view?.recording_type ?? null)}
              onSeek={
                sourceJobId
                  ? (ms) => {
                      setSeek({ ms, key: Date.now() });
                      setTab("transcript");
                    }
                  : undefined
              }
            />
            {generated && (
              <DetailToggle
                value={detail}
                onChange={(next) => {
                  setDetail(next);
                  writeDetail(noteId, next);
                }}
              />
            )}
            {generated && editable && (
              <CorrectionsPanel noteId={noteId} rows={genRows} version={version} onChanged={load} />
            )}
            <CarriedItems noteId={noteId} readOnly={!editable} />
            {blocks.length === 0 && (
              <div className="section-ro empty-val">
                {transcriptDefs.length > 0 ? "No notes yet — the transcript is under the other tab." : "Nothing here yet."}
              </div>
            )}
            {blocks.map((block) => {
              const badge =
                (block.key === "action_items" || block.key === "next_steps") && responseCount > 0 ? (
                  <button type="button" className="chip version response-badge" onClick={() => setTab("responses")}>
                    {responseCount} response{responseCount === 1 ? "" : "s"}
                  </button>
                ) : null;
              return (
                <section key={block.key} className={`doc-section${block.title ? "" : " untitled"}`}>
                  <div className="field">
                    {(block.title || badge) && (
                      <span className="section-name">
                        {block.title}
                        {badge}
                      </span>
                    )}
                    <SectionField
                      def={defFor(block)}
                      section={sectionOf(shownContent, block.key)}
                      readOnly={!editable}
                      onChange={(next) => onContentChange(withSection(shownContent, next))}
                      lineExtra={lineExtra}
                    />
                    {alsoSaid && (alsoSaid.get(block.key)?.length ?? 0) > 0 && (
                      <div className="also-said">
                        <span className="muted">Also said</span>
                        <ul className="rt-list">
                          {(alsoSaid.get(block.key) ?? []).map((row) => (
                            <li key={row.item_key}>
                              <span>
                                {row.text}
                                <LineEvidence noteId={noteId} row={row} rowsByKey={genByKey} />
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </section>
              );
            })}
          </div>
        )}

        {/* Ask this note. It hangs off the foot of the document, so the
            answer arrives under the text it is about — and it is offered
            for the note as it stands, never for an old version you are
            only looking at. */}
        {!viewing && <AskNote noteId={noteId} />}
      </div>

      {showVersions && (
        <aside className="panel versions-panel" aria-label="Version history">
          <div className="panel-h">
            <h3>History</h3>
            <span className="grow" />
            {versions && <span className="count">{versions.length}</span>}
          </div>
          {versions === null && (
            <div className="panel-b">
              <Skeleton style={{ height: 48 }} />
            </div>
          )}
          {versions?.map((v) => (
            <button
              key={v.id}
              className="ver-item"
              aria-current={viewing ? viewing.version_number === v.version_number : v.version_number === version}
              onClick={() => void openVersion(v)}
            >
              <span className="ver-num">
                <span className="mono">v{v.version_number}</span>
                {v.is_amendment && <span className="chip amended">{v.amendment_type ?? "amendment"}</span>}
              </span>
              <span className="ver-meta">{formatDateTime(v.created_at)}</span>
              {v.amendment_reason && <span className="ver-meta">“{v.amendment_reason}”</span>}
            </button>
          ))}
        </aside>
      )}

      {confirmDelete && (
        <ConfirmDialog
          title="Delete this note?"
          subtitle="It disappears from everyone's list and any public link stops working."
          confirmLabel="Delete"
          confirmDanger
          busy={busy}
          error={actionError}
          onConfirm={() => void onDelete()}
          onCancel={() => setConfirmDelete(false)}
        >
          The note is kept for the workspace's records but is no longer shown anywhere.
        </ConfirmDialog>
      )}

      {showShare && (
        <ShareDialog
          noteId={noteId}
          noteTitle={shownContent.title ?? ""}
          owner={
            identity && note.primary_author_id === identity.id
              ? { name: identity.display_name, email: identity.email, isMe: true }
              : note.primary_author_name
                ? { name: note.primary_author_name, email: "", isMe: false }
                : undefined
          }
          onClose={() => setShowShare(false)}
        />
      )}
    </div>
  );
}


// ── Q5: Short / Standard / Detailed ─────────────────────────────────

export type DetailLevel = "short" | "standard" | "detailed";
const DETAIL_KEY = "note-detail:";

function readDetail(noteId: string): DetailLevel {
  try {
    const value = window.localStorage.getItem(DETAIL_KEY + noteId);
    return value === "short" || value === "detailed" ? value : "standard";
  } catch {
    return "standard";
  }
}

function writeDetail(noteId: string, value: DetailLevel): void {
  try {
    window.localStorage.setItem(DETAIL_KEY + noteId, value);
  } catch {
    // A convenience; a browser that will not store it shows Standard next time.
  }
}

/** Short: the overview. Standard: the note as written. Detailed: plus the
 *  verified facts no line used, under their topic. A view — never an edit,
 *  never a model call. */
export function DetailToggle({ value, onChange }: { value: DetailLevel; onChange: (v: DetailLevel) => void }) {
  const options: [DetailLevel, string][] = [
    ["short", "Short"],
    ["standard", "Standard"],
    ["detailed", "Detailed"],
  ];
  return (
    <div className="seg detail-toggle" role="radiogroup" aria-label="How much to show">
      {options.map(([key, label]) => (
        <button
          key={key}
          type="button"
          role="radio"
          aria-checked={value === key}
          className={`seg-opt${value === key ? " on" : ""}`}
          onClick={() => onChange(key)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/** The fact rows no displayed line is, grouped by the section they belong
 *  under — what "Detailed" adds. */
export function uncitedBySection(
  rows: GeneratedItem[],
  content: { sections?: { section_key: string; text?: string | null }[] } | null,
): Map<string, GeneratedItem[]> {
  const shown = new Set<string>();
  for (const section of content?.sections ?? []) {
    for (const line of (section.text ?? "").split("\n")) if (line.trim()) shown.add(lineKey(line));
  }
  const cited = new Set(rows.flatMap((r) => r.cites ?? []).filter((k) => shown.has(k)));
  const out = new Map<string, GeneratedItem[]>();
  for (const row of rows) {
    if (row.placement !== "suggested" || shown.has(row.item_key) || cited.has(row.item_key)) continue;
    const list = out.get(row.section_key) ?? [];
    list.push(row);
    out.set(row.section_key, list);
  }
  return out;
}
