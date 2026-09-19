import React, { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { getResult, listJobs, setSpeakerNames } from "../api/asr";
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
  ResponseView,
  NoteContent,
  NoteEnvelope,
  NoteSection,
  NoteVersionDetail,
  NoteVersionSummary,
  ReadPurpose,
  TemplateSection,
  TranscriptResult,
  TranscriptTurn,
} from "../api/types";
import { defaultSpeakerName } from "../api/types";
import { AskNote } from "../components/AskNote";
import { ConfirmDialog } from "../components/ConfirmDialog";
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
  SparkleIcon,
  TrashIcon,
  UserIcon,
} from "../components/icons";
import { Menu, type MenuItem } from "../components/Menu";
import { RichText } from "../components/RichText";
import { isTranscript, parseRichText } from "../lib/richText";
import { speakerInitials, speakerTint } from "../lib/speakers";
import { ShareDialog } from "../components/ShareDialog";
import { Skeleton } from "../components/Skeleton";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toaster";
import { useAuth } from "../auth/AuthContext";
import { jobForNote, rememberLink } from "../lib/captures";
import { noteToMarkdown, safeFilename, saveBlob } from "../lib/exportNote";
import { formatDateTime, formatElapsed, relativeTime } from "../lib/time";
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
function FreeTextField({ def, section, readOnly, onChange }: FieldProps) {
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

  if (readOnly) return <RichText text={text} />;

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
        <RichText text={text} placeholder={placeholder} />
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

interface TranscriptViewProps {
  jobId: string;
  /** A speaker was renamed on the job — the note body may want to follow. */
  onSpeakerRenamed?: (from: string, to: string) => void;
  /** Shown instead of the error when the job cannot be read (the note's own text). */
  fallback?: ReactNode;
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

function TranscriptView({ jobId, onSpeakerRenamed, fallback }: TranscriptViewProps) {
  const toast = useToast();
  const [result, setResult] = useState<TranscriptResult | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState<{ label: string; value: string } | null>(null);
  const [saving, setSaving] = useState(false);

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

  const commitRename = async () => {
    if (!editing || saving) return;
    const { label, value } = editing;
    const from = names[label] ?? defaultSpeakerName(label);
    const to = value.trim() || defaultSpeakerName(label);
    setEditing(null);
    if (to === from) return;
    const next = customNames(names);
    if (to === defaultSpeakerName(label)) delete next[label];
    else next[label] = to;
    setSaving(true);
    try {
      const res = await setSpeakerNames(jobId, next);
      const merged: Record<string, string> = {};
      for (const l of result?.speakers ?? []) merged[l] = res.speaker_names[l] ?? defaultSpeakerName(l);
      setNames(merged);
      onSpeakerRenamed?.(from, merged[label] ?? to);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSaving(false);
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
  return (
    <div className="transcript">
      <div className="transcript-bar">
        <span className="help">
          {turns.length === 0
            ? "Nothing was said."
            : !diarized
              ? "Speakers were not told apart in this recording."
              : `${speakerCount === 1 ? "1 speaker" : `${speakerCount} speakers`} · click a name to rename`}
        </span>
        <span className="grow" />
        <button className="btn ghost sm" onClick={() => void copy()} disabled={turns.length === 0}>
          {copied ? <CheckIcon size={14} /> : <CopyIcon size={14} />} {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {turns.map((t, i) => {
        const name = turnName(t, names);
        const isEditing = editing !== null && t.speaker !== null && editing.label === t.speaker;
        return (
          <div key={i} className="turn">
            {diarized && (
              <span className="speaker-avatar" style={{ "--tint": speakerTint(name) } as React.CSSProperties} aria-hidden="true">
                {speakerInitials(name)}
              </span>
            )}
            <div className="turn-h">
              {diarized &&
                (isEditing ? (
                  <input
                    className="input speaker-input"
                    aria-label="Speaker name"
                    autoFocus
                    value={editing.value}
                    maxLength={80}
                    onChange={(e) => setEditing({ label: editing.label, value: e.target.value })}
                    onBlur={() => void commitRename()}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void commitRename();
                      if (e.key === "Escape") setEditing(null);
                    }}
                  />
                ) : t.speaker ? (
                  <button
                    type="button"
                    className="turn-speaker"
                    title="Rename this speaker"
                    disabled={saving}
                    onClick={() => setEditing({ label: t.speaker!, value: name })}
                  >
                    {name}
                  </button>
                ) : (
                  <span className="turn-speaker unknown">{UNKNOWN_SPEAKER}</span>
                ))}
              <span className="turn-time mono">{formatElapsed(t.start_ms)}</span>
            </div>
            {t.paragraphs.map((p, j) => (
              <p key={j} className="turn-text">
                {p}
              </p>
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

type Tab = "notes" | "transcript" | "responses";

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
  const [version, setVersion] = useState(0);
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
  const onSpeakerRenamed = (from: string, to: string) => {
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
      sections: sections.map((def) => ({
        name: def.name,
        text: sectionOf(shownContent, def.id).text ?? "",
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
  const noteDefs = (sections ?? []).filter((def) => !transcriptDefs.includes(def));
  const hasTranscript = sourceJobId !== null || transcriptDefs.length > 0;
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
          {templateName && (
            <span className="doc-pill tpl" title="The template this note was written from">
              <SparkleIcon size={13} />
              {templateName}
            </span>
          )}
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

        {(hasTranscript || hasResponsesTab) && (
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
          </div>
        )}

        {tab === "responses" && hasResponsesTab ? (
          <ResponsesPanel
            noteId={noteId}
            items={items}
            responses={responses}
            sections={sections}
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
            return sourceJobId ? <TranscriptView jobId={sourceJobId} onSpeakerRenamed={onSpeakerRenamed} fallback={textView} /> : textView;
          })()
        ) : (
          <div className="doc-body">
            {sections.length === 0 && <div className="section-ro empty-val">This note's template has no sections.</div>}
            {noteDefs.length === 0 && sections.length > 0 && (
              <div className="section-ro empty-val">No notes yet — the transcript is under the other tab.</div>
            )}
            {noteDefs.map((def) => (
              <section key={def.id} className="doc-section">
                <div className="field">
                  <span className="section-name">
                    {def.name}
                    {def.required && <span className="req-tag">required</span>}
                    {(def.id === "action_items" || def.id === "next_steps") && responseCount > 0 && (
                      <button type="button" className="chip version response-badge" onClick={() => setTab("responses")}>
                        {responseCount} response{responseCount === 1 ? "" : "s"}
                      </button>
                    )}
                  </span>
                  <SectionField
                    def={def}
                    section={sectionOf(shownContent, def.id)}
                    readOnly={!editable}
                    onChange={(next) => onContentChange(withSection(shownContent, next))}
                  />
                </div>
              </section>
            ))}
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
