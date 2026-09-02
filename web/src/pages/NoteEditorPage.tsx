import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, errorMessage } from "../api/http";
import {
  amendNote,
  downloadPdf,
  finalizeNote,
  getNote,
  getTemplate,
  getVersion,
  listVersions,
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
} from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { DownloadIcon, HistoryIcon } from "../components/icons";
import { Skeleton } from "../components/Skeleton";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toaster";
import { formatDateTime, relativeTime } from "../lib/time";

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
    return (
      <div className={`section-ro ${text ? "" : "empty-val"}`}>{text || "Nothing entered."}</div>
    );
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
      nextSel = selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value];
    } else {
      nextSel = selected[0] === value ? [] : [value];
    }
    const label = (v: string) => def.options?.find((o) => o.value === v)?.label ?? v;
    onChange({
      ...section,
      text: nextSel.map(label).join(", "),
      field_specific_metadata: manualMeta(
        nextSel.length === 0 ? null : { selected: multi ? nextSel : nextSel[0] },
      ),
    });
  };

  return (
    <div className="seg" role="group" aria-label={def.name}>
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
    <div className="numeric-row">
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
    <div className="numeric-row">
      <input
        className="input num"
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

// ── the page ──────────────────────────────────────────────────────────

export function NoteEditorPage() {
  const { noteId = "" } = useParams();
  const toast = useToast();

  const [note, setNote] = useState<NoteEnvelope | null>(null);
  const [sections, setSections] = useState<TemplateSection[] | null>(null);
  const [content, setContent] = useState<NoteContent | null>(null);
  const [version, setVersion] = useState(0);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [conflict, setConflict] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [versions, setVersions] = useState<NoteVersionSummary[] | null>(null);
  const [showVersions, setShowVersions] = useState(false);
  const [viewing, setViewing] = useState<NoteVersionDetail | null>(null);

  const [confirmFinalize, setConfirmFinalize] = useState(false);
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
          setSections(
            [...tpl.schema_jsonb.sections].sort((a, b) => (a.order ?? 0) - (b.order ?? 0)),
          );
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

  const onPdf = async () => {
    try {
      const blob = await downloadPdf(noteId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${note?.code ?? "note"}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(errorMessage(err));
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
        return "Unsaved changes";
      case "error":
        return conflict ? "Out of date" : "Save failed";
      default:
        return `Saved · v${version}`;
    }
  }, [saveState, conflict, version]);

  if (loadError) {
    return (
      <div className="card" style={{ padding: "var(--s-6)" }}>
        <div className="banner banner-danger" role="alert">
          {loadError}
        </div>
        <div className="center-row" style={{ marginTop: "var(--s-4)" }}>
          <button className="btn" onClick={() => void load()}>
            Try again
          </button>
          <Link to="/" className="btn btn-ghost" style={{ textDecoration: "none" }}>
            Back to notes
          </Link>
        </div>
      </div>
    );
  }

  if (!note || !shownContent || sections === null) {
    return (
      <div aria-busy="true" aria-label="Loading note">
        <Skeleton style={{ height: 40, width: "50%", marginBottom: "var(--s-5)" }} />
        <div className="editor-main">
          <div className="card section-block">
            <Skeleton style={{ height: 90 }} />
          </div>
          <div className="card section-block">
            <Skeleton style={{ height: 90 }} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="editor-head">
        <input
          className="title-input"
          value={shownContent.title ?? ""}
          placeholder="Untitled note"
          aria-label="Note title"
          disabled={!editable}
          onChange={(e) => onContentChange({ ...shownContent, title: e.target.value })}
        />
        <div className="row">
          <StatusBadge status={viewing ? `v${viewing.version_number}` : note.status} />
          <span className="code-tag">{note.code}</span>
          {isDraft && !viewing && (
            <span className={`save-state ${saveState}`} role="status">
              <span className="sdot" aria-hidden="true" />
              {saveLabel}
            </span>
          )}
          <span style={{ flex: 1 }} />
          {viewing && (
            <button className="btn btn-sm" onClick={() => setViewing(null)}>
              Back to current
            </button>
          )}
          {!viewing && isDraft && (
            <button
              className="btn btn-primary btn-sm"
              onClick={() => {
                setActionError(null);
                setConfirmFinalize(true);
              }}
            >
              Finalize
            </button>
          )}
          {!viewing && note.status === "finalized" && !amending && (
            <>
              <button className="btn btn-sm" onClick={() => setAmending(true)}>
                Amend
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => void onRevert()} disabled={busy}>
                Revert to draft
              </button>
            </>
          )}
          {!viewing && note.status === "amended" && !amending && (
            <button className="btn btn-sm" onClick={() => setAmending(true)}>
              Amend again
            </button>
          )}
          <button className="btn btn-ghost btn-sm" onClick={() => void onPdf()}>
            <DownloadIcon /> PDF
          </button>
          <button
            className="btn btn-ghost btn-sm"
            aria-pressed={showVersions}
            onClick={() => void toggleVersions()}
          >
            <HistoryIcon /> History
          </button>
        </div>
        {conflict && (
          <div className="banner banner-warn" role="alert">
            Someone else saved a newer version of this note.{" "}
            <button className="btn btn-sm" onClick={() => void load()} style={{ marginLeft: 8 }}>
              Reload latest
            </button>
          </div>
        )}
        {amending && (
          <div className="card amend-bar">
            <h3>Recording an amendment</h3>
            <div className="row">
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
              <button className="btn btn-primary btn-sm" onClick={() => void onSaveAmendment()} disabled={busy}>
                {busy ? "Saving…" : "Save amendment"}
              </button>
              <button
                className="btn btn-ghost btn-sm"
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
      </div>

      <div className="editor-layout">
        <div className="editor-main">
          {sections.length === 0 && (
            <div className="card section-block">
              <div className="section-ro empty-val">This note's template has no sections.</div>
            </div>
          )}
          {sections.map((def) => (
            <section key={def.id} className="card section-block">
              <div className="field">
                <span className="section-name">
                  {def.name}
                  {def.required ? " *" : ""}
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

        {showVersions && (
          <aside className="card versions-panel" aria-label="Version history">
            <h3>History</h3>
            {versions === null && <Skeleton style={{ height: 60 }} />}
            {versions?.map((v) => (
              <button
                key={v.id}
                className="ver-item"
                aria-current={
                  viewing ? viewing.version_number === v.version_number : v.version_number === version
                }
                onClick={() => void openVersion(v)}
              >
                <span className="v-num">
                  v{v.version_number}
                  {v.is_amendment ? ` · ${v.amendment_type ?? "amendment"}` : ""}
                </span>
                <span className="v-meta">{formatDateTime(v.created_at)}</span>
                {v.amendment_reason && <span className="v-meta">“{v.amendment_reason}”</span>}
              </button>
            ))}
          </aside>
        )}
      </div>

      <p className="page-sub" style={{ marginTop: "var(--s-5)" }}>
        Last updated {relativeTime(note.updated_at)}
      </p>

      {confirmFinalize && (
        <ConfirmDialog
          title="Finalize this note?"
          confirmLabel="Finalize"
          busy={busy}
          error={actionError}
          onConfirm={() => void onFinalize()}
          onCancel={() => setConfirmFinalize(false)}
        >
          Finalizing freezes the current version. You can still amend it later — every
          amendment is recorded in the note's history.
        </ConfirmDialog>
      )}
    </>
  );
}
