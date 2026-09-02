import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { cancelJob, listJobs, submitJob } from "../api/asr";
import { errorMessage } from "../api/http";
import { createFromTranscript, listTemplates } from "../api/notes";
import type { AsrJob, TemplateSummary } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { MicIcon, StopIcon, UploadIcon } from "../components/icons";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toaster";
import { formatElapsed, relativeTime } from "../lib/time";

const LEVEL_BARS = 24;
const POLL_MS = 4000;
const TITLE_STORE = "notesai.capture.titles";

// ── per-job meeting titles (survive a reload until the note is made) ──

function loadTitles(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(TITLE_STORE) ?? "{}") as Record<string, string>;
  } catch {
    return {};
  }
}

function rememberTitle(jobId: string, title: string) {
  const all = loadTitles();
  if (title) all[jobId] = title;
  localStorage.setItem(TITLE_STORE, JSON.stringify(all));
}

// ── microphone recorder hook ──────────────────────────────────────────

interface PendingAudio {
  blob: Blob;
  filename: string;
  url: string;
}

function pickMimeType(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  return candidates.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
}

function useRecorder(onDone: (audio: PendingAudio) => void, onError: (msg: string) => void) {
  const [recording, setRecording] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [levels, setLevels] = useState<number[]>(() => Array(LEVEL_BARS).fill(0));

  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const audioCtx = useRef<AudioContext | null>(null);
  const raf = useRef(0);
  const timer = useRef(0);

  const cleanup = useCallback(() => {
    cancelAnimationFrame(raf.current);
    window.clearInterval(timer.current);
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    void audioCtx.current?.close().catch(() => undefined);
    audioCtx.current = null;
    recorder.current = null;
    setLevels(Array(LEVEL_BARS).fill(0));
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const start = useCallback(async () => {
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.current = media;

      // Level meter: RMS of the analyser frame, pushed into a rolling strip.
      const ctx = new AudioContext();
      audioCtx.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(media).connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);
      const tick = () => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (const v of buf) {
          const c = (v - 128) / 128;
          sum += c * c;
        }
        const rms = Math.min(1, Math.sqrt(sum / buf.length) * 3);
        setLevels((prev) => [...prev.slice(1), rms]);
        raf.current = requestAnimationFrame(tick);
      };
      raf.current = requestAnimationFrame(tick);

      const mimeType = pickMimeType();
      const rec = new MediaRecorder(media, mimeType ? { mimeType } : undefined);
      const chunks: BlobPart[] = [];
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data);
      };
      rec.onstop = () => {
        const type = rec.mimeType || "audio/webm";
        const ext = type.includes("mp4") ? "m4a" : "webm";
        const blob = new Blob(chunks, { type });
        cleanup();
        setRecording(false);
        if (blob.size === 0) {
          onError("The recording came out empty — check the microphone.");
          return;
        }
        onDone({
          blob,
          filename: `meeting-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}.${ext}`,
          url: URL.createObjectURL(blob),
        });
      };
      recorder.current = rec;
      rec.start(1000);

      const startedAt = Date.now();
      setElapsedMs(0);
      timer.current = window.setInterval(() => setElapsedMs(Date.now() - startedAt), 250);
      setRecording(true);
    } catch (err) {
      cleanup();
      onError(
        err instanceof DOMException && err.name === "NotAllowedError"
          ? "Microphone access was denied — allow it in the browser and try again."
          : errorMessage(err),
      );
    }
  }, [cleanup, onDone, onError]);

  const stop = useCallback(() => {
    recorder.current?.stop();
  }, []);

  return { recording, elapsedMs, levels, start, stop };
}

// ── the page ──────────────────────────────────────────────────────────

export function CapturePage() {
  const toast = useToast();
  const navigate = useNavigate();

  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState<"en" | "uk">("en");
  const [diarize, setDiarize] = useState(true);
  const [hint, setHint] = useState("");
  const [pending, setPending] = useState<PendingAudio | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [drag, setDrag] = useState(false);

  const [jobs, setJobs] = useState<AsrJob[] | null>(null);
  const [titles, setTitles] = useState<Record<string, string>>(loadTitles);

  const [noteJob, setNoteJob] = useState<AsrJob | null>(null);
  const [templates, setTemplates] = useState<TemplateSummary[] | null>(null);
  const [templateId, setTemplateId] = useState<string>("");
  const [creating, setCreating] = useState(false);

  const onRecorded = useCallback((audio: PendingAudio) => setPending(audio), []);
  const onRecordError = useCallback((msg: string) => toast.error(msg), [toast]);
  const rec = useRecorder(onRecorded, onRecordError);

  // ── jobs list + polling while anything is in flight ─────────────────

  const refreshJobs = useCallback(async () => {
    try {
      setJobs(await listJobs());
    } catch {
      /* transient — keep the last list */
    }
  }, []);

  useEffect(() => {
    void refreshJobs();
  }, [refreshJobs]);

  const hasActive = jobs?.some((j) => j.status === "queued" || j.status === "running") ?? false;
  useEffect(() => {
    if (!hasActive) return;
    const t = window.setInterval(() => void refreshJobs(), POLL_MS);
    return () => window.clearInterval(t);
  }, [hasActive, refreshJobs]);

  // ── submit ──────────────────────────────────────────────────────────

  const discardPending = () => {
    if (pending) URL.revokeObjectURL(pending.url);
    setPending(null);
  };

  const onSubmit = async () => {
    if (!pending) return;
    setSubmitting(true);
    try {
      const job = await submitJob({
        audio: pending.blob,
        filename: pending.filename,
        language,
        diarize,
        vocabularyHint: hint,
      });
      rememberTitle(job.id, title.trim());
      setTitles(loadTitles());
      discardPending();
      setTitle("");
      toast.success(diarize ? "Uploaded — transcribing with speaker separation" : "Uploaded — transcribing");
      await refreshJobs();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const onFile = (file: File | undefined | null) => {
    if (!file) return;
    if (pending) URL.revokeObjectURL(pending.url);
    setPending({ blob: file, filename: file.name, url: URL.createObjectURL(file) });
  };

  // ── create note from a finished job ─────────────────────────────────

  const openNoteDialog = async (job: AsrJob) => {
    setNoteJob(job);
    setTemplateId("");
    if (templates === null) {
      try {
        const list = await listTemplates();
        setTemplates(list.filter((t) => t.status !== "archived"));
        const meeting = list.find((t) => t.code.startsWith("meeting_notes") && t.language === job.language);
        setTemplateId(meeting?.id ?? list.find((t) => t.code.startsWith("meeting_notes"))?.id ?? "");
      } catch (err) {
        toast.error(errorMessage(err));
        setTemplates([]);
      }
    } else {
      const meeting = templates.find(
        (t) => t.code.startsWith("meeting_notes") && t.language === job.language,
      );
      setTemplateId(meeting?.id ?? "");
    }
  };

  const onCreateNote = async () => {
    if (!noteJob) return;
    setCreating(true);
    try {
      const res = await createFromTranscript({
        asr_job_id: noteJob.id,
        template_id: templateId || undefined,
        title: titles[noteJob.id] || undefined,
      });
      toast.success(`Note ${res.code} created`);
      navigate(`/notes/${res.id}`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setCreating(false);
    }
  };

  // ── render ──────────────────────────────────────────────────────────

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Capture</h1>
          <p className="page-sub">
            Record a meeting here, or upload a recording — get a speaker-attributed note.
          </p>
        </div>
      </div>

      <div className="capture-grid">
        {/* record */}
        <div className="card rec-card">
          {!rec.recording && !pending && (
            <>
              <div className="level-meter" aria-hidden="true">
                {rec.levels.map((_, i) => (
                  <span key={i} className="bar" style={{ height: 4 }} />
                ))}
              </div>
              <button className="btn btn-primary btn-lg" onClick={() => void rec.start()}>
                <MicIcon /> Start recording
              </button>
              <p className="hint">Uses this device's microphone. Best placed mid-table.</p>
            </>
          )}

          {rec.recording && (
            <>
              <div className="rec-timer">
                <span className="rec-dot" aria-hidden="true" />
                <span aria-live="polite">{formatElapsed(rec.elapsedMs)}</span>
              </div>
              <div className="level-meter live" aria-hidden="true">
                {rec.levels.map((lvl, i) => (
                  <span key={i} className="bar" style={{ height: Math.max(4, Math.round(lvl * 48)) }} />
                ))}
              </div>
              <button className="btn btn-danger btn-lg" onClick={rec.stop}>
                <StopIcon /> Stop
              </button>
            </>
          )}

          {pending && !rec.recording && (
            <>
              <div className="pending-audio">
                <audio controls src={pending.url} aria-label="Recorded audio preview" />
              </div>
              <p className="hint">{pending.filename}</p>
              <div className="center-row">
                <button className="btn btn-ghost" onClick={discardPending}>
                  Discard
                </button>
              </div>
            </>
          )}
        </div>

        {/* upload */}
        <label
          className={`card dropzone ${drag ? "drag" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            onFile(e.dataTransfer.files?.[0]);
          }}
        >
          <UploadIcon />
          <strong>Drop a recording</strong>
          <span className="hint">or click to choose — wav, mp3, m4a, ogg, webm</span>
          <input
            type="file"
            accept="audio/*,.m4a,.webm,.ogg"
            style={{ display: "none" }}
            onChange={(e) => {
              onFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </label>
      </div>

      {/* options + submit */}
      <div className="card capture-form">
        <div className="opts">
          <div className="field" style={{ flex: 1, minWidth: 220 }}>
            <span className="label">Meeting title</span>
            <input
              className="input"
              placeholder="e.g. Q3 pipeline review"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div className="field">
            <span className="label">Language</span>
            <div className="seg" role="group" aria-label="Language">
              {(["en", "uk"] as const).map((l) => (
                <button
                  key={l}
                  type="button"
                  className="seg-opt"
                  aria-pressed={language === l}
                  onClick={() => setLanguage(l)}
                >
                  {l === "en" ? "English" : "Українська"}
                </button>
              ))}
            </div>
          </div>
          <label className="toggle">
            <input type="checkbox" checked={diarize} onChange={(e) => setDiarize(e.target.checked)} />
            <span className="track" aria-hidden="true" />
            Separate speakers
          </label>
        </div>
        <div className="field">
          <span className="label">Vocabulary hint (optional)</span>
          <input
            className="input"
            placeholder="Names, product terms, acronyms the recording uses…"
            maxLength={2000}
            value={hint}
            onChange={(e) => setHint(e.target.value)}
          />
        </div>
        <div className="center-row">
          <button
            className="btn btn-primary btn-lg"
            disabled={!pending || submitting || rec.recording}
            onClick={() => void onSubmit()}
          >
            {submitting ? "Uploading…" : "Transcribe"}
          </button>
        </div>
      </div>

      {/* jobs */}
      <h2 className="section-title">Transcriptions</h2>
      {jobs !== null && jobs.length === 0 && (
        <div className="card">
          <EmptyState
            icon={<MicIcon size={26} />}
            title="No transcriptions yet"
            message="Your uploaded and recorded meetings will appear here while they process."
          />
        </div>
      )}
      {jobs?.map((job) => (
        <div key={job.id} className="card job-row">
          <div className="job-main">
            <div className="job-title">
              <strong>{titles[job.id] || "Untitled capture"}</strong>
              <span className="lang-tag">{job.language}</span>
              {job.diarize && <span className="lang-tag">speakers</span>}
            </div>
            <div className="job-sub">
              {job.status === "running" && job.started_at
                ? `Started ${relativeTime(job.started_at)}`
                : `Queued ${relativeTime(job.queued_at)}`}
            </div>
            {job.status === "failed" && job.error_message && (
              <div className="job-err" role="alert">
                {job.error_message} {job.error_kind && <span className="err-kind">{job.error_kind}</span>}
              </div>
            )}
          </div>
          <StatusBadge status={job.status} />
          {(job.status === "queued" || job.status === "running") && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() =>
                void cancelJob(job.id)
                  .then(refreshJobs)
                  .catch((err) => toast.error(errorMessage(err)))
              }
            >
              Cancel
            </button>
          )}
          {job.status === "complete" && (
            <button className="btn btn-primary btn-sm" onClick={() => void openNoteDialog(job)}>
              Create note
            </button>
          )}
        </div>
      ))}

      {/* create-note dialog */}
      {noteJob && (
        <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && setNoteJob(null)}>
          <div className="modal" role="dialog" aria-modal="true" aria-label="Create note from transcript">
            <h2>Create a note</h2>
            <div className="modal-body">
              <div className="field">
                <span className="label">Template</span>
                <select
                  className="select"
                  value={templateId}
                  onChange={(e) => setTemplateId(e.target.value)}
                >
                  <option value="">Auto-select from the transcript</option>
                  {templates?.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name} ({t.language})
                    </option>
                  ))}
                </select>
              </div>
              <p className="hint" style={{ marginTop: "var(--s-2)" }}>
                {titles[noteJob.id]
                  ? `Titled “${titles[noteJob.id]}”. `
                  : ""}
                Speaker-separated transcripts become dialogue in the note.
              </p>
            </div>
            <div className="modal-actions">
              <button className="btn btn-ghost" onClick={() => setNoteJob(null)} disabled={creating}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={() => void onCreateNote()} disabled={creating}>
                {creating ? "Creating…" : "Create note"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
