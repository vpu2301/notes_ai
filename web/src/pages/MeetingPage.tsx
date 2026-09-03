import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { submitJob } from "../api/asr";
import { errorMessage } from "../api/http";
import { languageName, type AsrLanguage } from "../api/types";
import { AlertIcon, MicIcon, StopIcon, UploadIcon } from "../components/icons";
import { useToast } from "../components/Toaster";
import { markMine, rememberTitle } from "../lib/captures";
import { formatElapsed } from "../lib/time";
import { useCaptures } from "../lib/useCaptures";
import { useRecorder, type RecordedAudio } from "../lib/useRecorder";

type Phase = "idle" | "uploading" | "processing";

const LANGUAGES: ReadonlyArray<readonly [AsrLanguage, string]> = [
  ["auto", "Detect"],
  ["en", "English"],
  ["uk", "Українська"],
  ["de", "Deutsch"],
];

/**
 * One screen, one button. Type a title (optional), press Record, press Stop.
 * The recording uploads itself, transcribes, becomes a note, and the note
 * opens — no "transcribe" step, no "create note" step.
 */
export function MeetingPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [params] = useSearchParams();

  // A calendar event's title arrives as ?title= from the home page's
  // "Start" button; otherwise the field starts empty.
  const [title, setTitle] = useState(() => params.get("title")?.slice(0, 200) ?? "");
  // Auto by default: the transcript and the note come out in whatever
  // language the meeting was held in. Pinning is an option, not a step.
  const [language, setLanguage] = useState<AsrLanguage>("auto");
  const [diarize, setDiarize] = useState(true);
  const [hint, setHint] = useState("");
  const [showOptions, setShowOptions] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const { captures, noteErrors, createNote, cancel, refresh } = useCaptures({
    onNoteReady: (jid, noteId) => {
      if (jid === jobId) navigate(`/notes/${noteId}`, { replace: true });
    },
  });

  // Latest submit settings, readable from the recorder's onstop closure.
  const settings = useRef({ title, language, diarize, hint });
  settings.current = { title, language, diarize, hint };

  const submit = useCallback(
    async (audio: RecordedAudio) => {
      const s = settings.current;
      setPhase("uploading");
      try {
        const job = await submitJob({
          audio: audio.blob,
          filename: audio.filename,
          language: s.language,
          diarize: s.diarize,
          vocabularyHint: s.hint,
        });
        rememberTitle(job.id, s.title);
        markMine(job.id);
        setJobId(job.id);
        setPhase("processing");
        void refresh();
      } catch (err) {
        toast.error(errorMessage(err));
        setPhase("idle");
      }
    },
    [refresh, toast],
  );

  const onRecordError = useCallback((msg: string) => toast.error(msg), [toast]);
  const rec = useRecorder(submit, onRecordError);

  // Don't let a tab close eat a recording.
  useEffect(() => {
    if (!rec.recording && phase !== "uploading") return;
    const onUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, [rec.recording, phase]);

  const onFile = (file: File | undefined | null) => {
    if (!file) return;
    void submit({ blob: file, filename: file.name });
  };

  const job = jobId ? captures?.find((c) => c.job.id === jobId)?.job ?? null : null;
  const uploadFirst = params.get("mode") === "upload";

  // ── processing view ─────────────────────────────────────────────────

  if (phase !== "idle") {
    const detected = languageName(job?.detected_language);
    const failed = job?.status === "failed";
    const cancelled = job?.status === "cancelled";
    const noteError = job && job.status === "complete" ? noteErrors[job.id] : undefined;
    return (
      <div className="meeting">
        <div className="meeting-stage">
          {job && noteError ? (
            <>
              <span className="stage-ico rec">
                <AlertIcon size={20} />
              </span>
              <h2>Couldn't write the note</h2>
              <p className="help">{noteError}</p>
              <div className="stage-actions">
                <button
                  className="btn primary"
                  onClick={() => void createNote(job).catch((err) => toast.error(errorMessage(err)))}
                >
                  Try again
                </button>
                <Link to="/" className="btn ghost">
                  Back to notes
                </Link>
              </div>
            </>
          ) : failed || cancelled ? (
            <>
              <span className="stage-ico rec">
                <AlertIcon size={20} />
              </span>
              <h2>{cancelled ? "Transcription cancelled" : "Transcription failed"}</h2>
              <p className="help">{job?.error_message ?? "Something went wrong on the way to a note."}</p>
              <div className="stage-actions">
                <button
                  className="btn primary"
                  onClick={() => {
                    setJobId(null);
                    setPhase("idle");
                  }}
                >
                  Try again
                </button>
                <Link to="/" className="btn ghost">
                  Back to notes
                </Link>
              </div>
            </>
          ) : (
            <>
              <span className="stage-ico live" aria-hidden="true">
                <span className="stage-pulse" />
              </span>
              <h2>{title.trim() || "Untitled meeting"}</h2>
              <p className="stage-status" role="status" aria-live="polite">
                {phase === "uploading"
                  ? "Uploading the recording…"
                  : job?.status === "complete"
                    ? `Writing your note${detected ? ` in ${detected}` : ""}…`
                    : job?.status === "running"
                      ? "Transcribing… this takes about as long as the recording"
                      : "Waiting for a transcription slot…"}
              </p>
              <p className="help">You can leave — the note will show up in your list when it's ready.</p>
              <div className="stage-actions">
                <Link to="/" className="btn">
                  Back to notes
                </Link>
                {job && (job.status === "queued" || job.status === "running") && (
                  <button
                    className="btn ghost"
                    onClick={() => void cancel(job).catch((err) => toast.error(errorMessage(err)))}
                  >
                    Cancel
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    );
  }

  // ── idle / recording view ───────────────────────────────────────────

  return (
    <div
      className={`meeting ${drag ? "drag" : ""}`}
      onDragOver={(e) => {
        if (rec.recording) return;
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        if (!rec.recording) onFile(e.dataTransfer.files?.[0]);
      }}
    >
      <div className="meeting-head">
        <input
          className="title-input"
          placeholder="Untitled meeting"
          aria-label="Meeting title"
          value={title}
          autoFocus={!uploadFirst}
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>

      <div className={`meeting-stage ${rec.recording ? "live" : ""}`}>
        <div className={`level-meter ${rec.recording ? "live" : ""}`} aria-hidden="true">
          {rec.levels.map((lvl, i) => (
            <span
              key={i}
              className="bar"
              style={{ height: rec.recording ? Math.max(3, Math.round(lvl * 44)) : 3 + ((i * 7) % 9) }}
            />
          ))}
        </div>

        {rec.recording ? (
          <>
            <div className="rec-timer">
              <span className="rec-pulse" aria-hidden="true" />
              <span aria-live="polite">{formatElapsed(rec.elapsedMs)}</span>
            </div>
            <button className="btn rec lg" onClick={rec.stop}>
              <StopIcon size={14} /> Stop
            </button>
            <p className="help">Stopping uploads and transcribes the meeting straight away.</p>
          </>
        ) : (
          <>
            <button className="btn accent lg rec-start" onClick={() => void rec.start()} autoFocus={uploadFirst}>
              <MicIcon size={16} /> Record
            </button>
            <p className="help">
              Or{" "}
              <button className="link" onClick={() => fileInput.current?.click()}>
                upload a recording
              </button>{" "}
              — drop a file anywhere on this page.
            </p>
            <input
              ref={fileInput}
              type="file"
              accept="audio/*,.m4a,.webm,.ogg"
              style={{ display: "none" }}
              onChange={(e) => {
                onFile(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          </>
        )}
      </div>

      {!rec.recording && (
        <div className="meeting-options">
          <button className="disclosure" aria-expanded={showOptions} onClick={() => setShowOptions((v) => !v)}>
            Options
          </button>
          {showOptions && (
            <div className="meeting-options-body">
              <div className="field">
                <span className="label">Language</span>
                <div className="seg" role="group" aria-label="Language">
                  {LANGUAGES.map(([code, label]) => (
                    <button
                      key={code}
                      type="button"
                      className="seg-opt"
                      aria-pressed={language === code}
                      onClick={() => setLanguage(code)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <span className="help">
                  Detect listens to the recording and writes the transcript and note in that language.
                </span>
              </div>
              <label className="chk-row">
                <input type="checkbox" className="chk" checked={diarize} onChange={(e) => setDiarize(e.target.checked)} />
                Tell speakers apart
              </label>
              <div className="field">
                <span className="label">Words to listen for</span>
                <input
                  className="input"
                  placeholder="Names, product terms, acronyms…"
                  maxLength={2000}
                  value={hint}
                  onChange={(e) => setHint(e.target.value)}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {drag && (
        <div className="meeting-drop" aria-hidden="true">
          <UploadIcon size={22} /> Drop to transcribe
        </div>
      )}
    </div>
  );
}
