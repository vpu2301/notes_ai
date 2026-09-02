import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getResult, listJobs, setSpeakerNames } from "../api/asr";
import { ApiError, errorMessage } from "../api/http";
import {
  amendNote,
  deleteNote,
  downloadPdf,
  finalizeNote,
  getNote,
  getTemplate,
  getVersion,
  listVersions,
  notesBySourceJob,
  revertToDraft,
  updateDraft,
} from "../api/notes";
import type {
  FieldMetadata,
  NoteAmendmentType,
  NoteContent,
  NoteEnvelope,
  NoteSection,
  NoteVersionDetail,
  NoteVersionSummary,
  TemplateSection,
  TranscriptResult,
  TranscriptTurn,
} from "../api/types";
import { defaultSpeakerName } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import {
  AlertIcon,
  ArrowLeftIcon,
  CheckIcon,
  CopyIcon,
  DownloadIcon,
  FileDownIcon,
  HistoryIcon,
  PenIcon,
  ShareIcon,
  TrashIcon,
} from "../components/icons";
import { Menu, type MenuItem } from "../components/Menu";
import { ShareDialog } from "../components/ShareDialog";
import { Skeleton } from "../components/Skeleton";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toaster";
import { jobForNote, rememberLink } from "../lib/captures";
import { noteToMarkdown, safeFilename, saveBlob } from "../lib/exportNote";
import { formatDateTime, formatElapsed, relativeTime } from "../lib/time";

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

function FreeTextField({ def, section, readOnly, onChange }: FieldProps) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const text = section.text ?? "";

  // Auto-grow to fit content.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [text]);

  if (readOnly) {
    return <div className={`section-ro ${text ? "" : "empty-val"}`}>{text || "Nothing entered."}</div>;
  }
  return (
    <textarea
      ref={ref}
      className="textarea seamless"
      rows={2}
      value={text}
      placeholder={def.min_chars ? `At least ${def.min_chars} characters…` : "Start writing…"}
      aria-label={def.name}
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
}

function TranscriptView({ jobId, onSpeakerRenamed }: TranscriptViewProps) {
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

// ── the page ──────────────────────────────────────────────────────────

type Tab = "notes" | "transcript";

export function NoteEditorPage() {
  const { noteId = "" } = useParams();
  const toast = useToast();
  const navigate = useNavigate();

  const [note, setNote] = useState<NoteEnvelope | null>(null);
  const [sections, setSections] = useState<TemplateSection[] | null>(null);
  const [content, setContent] = useState<NoteContent | null>(null);
  const [version, setVersion] = useState(0);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [conflict, setConflict] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [tab, setTab] = useState<Tab>("notes");
  const [sourceJobId, setSourceJobId] = useState<string | null>(() => jobForNote(noteId));

  const [versions, setVersions] = useState<NoteVersionSummary[] | null>(null);
  const [showVersions, setShowVersions] = useState(false);
  const [viewing, setViewing] = useState<NoteVersionDetail | null>(null);

  const [confirmFinalize, setConfirmFinalize] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [showShare, setShowShare] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [amending, setAmending] = useState(false);
  const [amendType, setAmendType] = useState<NoteAmendmentType>("correction");
  const [amendReason, setAmendReason] = useState("");

  const saveTimer = useRef<number | null>(null);
  const latest = useRef<{ content: NoteContent; version: number } | null>(null);

  // ── load ────────────────────────────────────────────────────────────

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const env = await getNote(noteId);
      setNote(env);
      setContent(env.content ?? null);
      setVersion(env.current_version_number);
      setSaveState("saved");
      setConflict(false);
      setViewing(null);
      if (env.content?.template_id) {
        try {
          const tpl = await getTemplate(env.content.template_id);
          setSections([...tpl.schema_jsonb.sections].sort((a, b) => (a.order ?? 0) - (b.order ?? 0)));
        } catch {
          // Template unavailable (deprecated/permissions): fall back to the
          // envelope's section labels as plain free-text sections.
          setSections(
            (env.section_labels ?? []).map((l) => ({
              id: l.section_key,
              name: l.name.en || l.name.uk || l.section_key,
            })),
          );
        }
      } else {
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

  // ── autosave (drafts and live amendments share the debounce) ────────

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

  const isDraft = note?.status === "draft";
  const editable = (isDraft || amending) && !viewing;

  const onContentChange = (next: NoteContent) => {
    setContent(next);
    // Amendments are saved explicitly (one audited version), never autosaved.
    if (isDraft) scheduleSave(next, version);
  };

  // A speaker renamed in the transcript is renamed in the note too — the
  // draft's turn lines start with the name. A finalized note is a record;
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

  const onFinalize = async () => {
    setBusy(true);
    setActionError(null);
    try {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      await flushSave();
      await finalizeNote(noteId, version);
      setConfirmFinalize(false);
      toast.success("Note finalized");
      await load();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const onRevert = async () => {
    setBusy(true);
    try {
      await revertToDraft(noteId);
      toast.success("Back to draft");
      await load();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const onSaveAmendment = async () => {
    if (!content) return;
    if (!amendReason.trim()) {
      toast.error("An amendment needs a short reason — it goes on the record.");
      return;
    }
    setBusy(true);
    try {
      await amendNote(noteId, content, amendType, amendReason.trim());
      setAmending(false);
      setAmendReason("");
      toast.success("Amendment recorded");
      await load();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const fileBase = () => safeFilename(shownContent?.title ?? "", note?.code ?? "note");

  const onPdf = async () => {
    try {
      saveBlob(await downloadPdf(noteId), `${fileBase()}.pdf`);
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
        setVersions(await listVersions(noteId));
      } catch (err) {
        toast.error(errorMessage(err));
        setVersions([]);
      }
    }
  };

  const openVersion = async (v: NoteVersionSummary) => {
    if (v.version_number === version && !viewing) return;
    try {
      setViewing(await getVersion(noteId, v.version_number));
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  // ── render ──────────────────────────────────────────────────────────

  const shownContent = viewing ? viewing.content : content;
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
  if (!viewing && isDraft) {
    menu.push({
      label: "Finalize note",
      icon: <CheckIcon size={14} />,
      sep: true,
      onClick: () => {
        setActionError(null);
        setConfirmFinalize(true);
      },
    });
  }
  if (!viewing && (note.status === "finalized" || note.status === "amended") && !amending) {
    menu.push({
      label: note.status === "amended" ? "Amend again" : "Amend",
      icon: <PenIcon size={14} />,
      sep: true,
      onClick: () => setAmending(true),
    });
    if (note.status === "finalized") {
      menu.push({ label: "Revert to draft", onClick: () => void onRevert(), disabled: busy });
    }
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

  return (
    <div className="doc-wrap">
      <div className="doc">
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
            note.status !== "draft" && <StatusBadge status={note.status} />
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

        <input
          className="title-input"
          value={shownContent.title ?? ""}
          placeholder="Untitled note"
          aria-label="Note title"
          disabled={!editable}
          onChange={(e) => onContentChange({ ...shownContent, title: e.target.value })}
        />
        <div className="doc-meta">
          <span>{formatDateTime(note.created_at)}</span>
          <span className="sep">·</span>
          <span>Updated {relativeTime(note.updated_at)}</span>
          <span className="sep">·</span>
          <span className="mono">{note.code}</span>
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

        {amending && (
          <div className="amend-bar">
            <h3>
              <PenIcon size={14} /> Recording an amendment
            </h3>
            <div className="row-actions">
              <select
                className="select"
                value={amendType}
                aria-label="Amendment type"
                onChange={(e) => setAmendType(e.target.value as NoteAmendmentType)}
              >
                <option value="correction">Correction</option>
                <option value="addition">Addition</option>
                <option value="clarification">Clarification</option>
              </select>
              <input
                className="input"
                style={{ flex: 1, minWidth: 200 }}
                placeholder="Why is this changing? (kept on the record)"
                value={amendReason}
                onChange={(e) => setAmendReason(e.target.value)}
              />
              <button className="btn primary sm" onClick={() => void onSaveAmendment()} disabled={busy}>
                {busy ? "Saving…" : "Save amendment"}
              </button>
              <button
                className="btn ghost sm"
                disabled={busy}
                onClick={() => {
                  setAmending(false);
                  void load();
                }}
              >
                Discard
              </button>
            </div>
          </div>
        )}

        {sourceJobId && (
          <div className="tabs doc-tabs" role="tablist">
            <button className={`tab ${tab === "notes" ? "on" : ""}`} role="tab" aria-selected={tab === "notes"} onClick={() => setTab("notes")}>
              Notes
            </button>
            <button
              className={`tab ${tab === "transcript" ? "on" : ""}`}
              role="tab"
              aria-selected={tab === "transcript"}
              onClick={() => setTab("transcript")}
            >
              Transcript
            </button>
          </div>
        )}

        {tab === "transcript" && sourceJobId ? (
          <TranscriptView jobId={sourceJobId} onSpeakerRenamed={onSpeakerRenamed} />
        ) : (
          <div className="doc-body">
            {sections.length === 0 && <div className="section-ro empty-val">This note's template has no sections.</div>}
            {sections.map((def) => (
              <section key={def.id} className="doc-section">
                <div className="field">
                  <span className="section-name">
                    {def.name}
                    {def.required && <span className="req-tag">required</span>}
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

      {confirmFinalize && (
        <ConfirmDialog
          title="Finalize this note?"
          subtitle="Finalizing freezes the current version."
          confirmLabel="Finalize"
          busy={busy}
          error={actionError}
          onConfirm={() => void onFinalize()}
          onCancel={() => setConfirmFinalize(false)}
        >
          You can still amend it later — every amendment is recorded in the note's history with a typed
          reason.
        </ConfirmDialog>
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
        <ShareDialog noteId={noteId} noteTitle={shownContent.title ?? ""} onClose={() => setShowShare(false)} />
      )}
    </div>
  );
}
