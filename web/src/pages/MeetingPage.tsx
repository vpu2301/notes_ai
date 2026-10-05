import { useCallback, useEffect, useRef, useState } from "react";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { FIRST_RUN_KEY } from "../lib/storageKeys";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { submitJob, submitWithLayoutFallback } from "../api/asr";
import { glossaryHint } from "../api/glossary";
import { messageFor } from "../lib/errorCopy";
import {
  languageName,
  type AsrLanguage,
  type CaptureSource,
  type MeetingType,
} from "../api/types";
import { useAuthOptional } from "../auth/AuthContext";
import { MicIcon, StopIcon, UploadIcon } from "../components/icons";
import { useToast } from "../components/Toaster";
import { contextFields, meetingCalendar, readCaptureContext } from "../lib/captureContext";
import { markMine, rememberTitle } from "../lib/captures";
import { formatElapsed, formatOffset } from "../lib/time";
import { useCaptures } from "../lib/useCaptures";
import { useMeetingNote } from "../lib/useMeetingNote";
import { useRecorder, type RecordedAudio } from "../lib/useRecorder";

type Phase = "idle" | "uploading" | "processing";

const LANGUAGES: ReadonlyArray<readonly [AsrLanguage, string]> = [
  ["auto", "Detect"],
  ["en", "English"],
  ["uk", "Українська"],
  ["de", "Deutsch"],
];

// How many people spoke. Only an exact small number is a hint worth
// sending; "Auto" and "6+" leave the count to the diarizer.
type People = "auto" | 1 | 2 | 3 | 4 | 5 | "6+";
const PEOPLE: ReadonlyArray<readonly [People, string]> = [
  ["auto", "Auto"],
  [1, "1"],
  [2, "2"],
  [3, "3"],
  [4, "4"],
  [5, "5"],
  ["6+", "6+"],
];

// What kind of meeting this is — picks the template family the note is
// written into. "Auto" is the default and is always right enough.
const MEETING_TYPES: ReadonlyArray<readonly [MeetingType, string]> = [
  ["auto", "Auto"],
  ["client", "Client"],
  ["team", "Team"],
  ["sales", "Sales"],
  ["one_on_one", "1:1"],
  ["interview", "Interview"],
];

/**
 * One screen, one button. Type a title (optional), press Record, press Stop.
 *
 * Sprint 34: pressing Record also OPENS THE NOTE. What the author types
 * while the meeting runs is the highest-value signal there is about what
 * matters, so there is now somewhere to type it — and it is the note
 * itself, autosaved, on every device, kept verbatim.
 */
/** Sprint I3: "also record this tab's audio" — a per-browser preference. */
const SYSTEM_AUDIO_KEY = "notesai.capture.systemAudio";

export function MeetingPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [params] = useSearchParams();
  // The author's own name labels their microphone's speaker ("Me").
  const displayName = useAuthOptional()?.displayName;

  // A calendar event's title arrives as ?title= from the home page's
  // "Start" button; otherwise the field starts empty.
  const [title, setTitle] = useState(() => params.get("title")?.slice(0, 200) ?? "");
  useDocumentTitle(title.trim() || "New meeting");
  // Sprint 30: its invitees wait in sessionStorage under ?event= (names
  // never ride the URL). They bound the speaker count and are offered as
  // names when renaming speakers. Sprint 34: they also go on the note,
  // together with the invite's agenda.
  const [eventCtx] = useState(() => readCaptureContext(params.get("event")));
  // Sprint 21: `/meeting/new?first_run=1` is where a new workspace lands.
  // Shown once per browser; a per-viewer convenience, so localStorage.
  const [firstRun, setFirstRun] = useState(() => {
    if (params.get("first_run") !== "1") return false;
    try {
      return window.localStorage.getItem(FIRST_RUN_KEY) !== "1";
    } catch {
      return true;
    }
  });
  const dismissFirstRun = () => {
    setFirstRun(false);
    try {
      window.localStorage.setItem(FIRST_RUN_KEY, "1");
    } catch {
      /* private mode */
    }
  };
  // Auto by default: the transcript and the note come out in whatever
  // language the meeting was held in. Pinning is an option, not a step.
  const [language, setLanguage] = useState<AsrLanguage>("auto");
  const [meetingType, setMeetingType] = useState<MeetingType>("auto");
  const [diarize, setDiarize] = useState(true);
  // Me / Them: the tab audio as a second channel. Off until asked for,
  // then remembered in this browser.
  const [systemAudio, setSystemAudioState] = useState(() => {
    try {
      return window.localStorage.getItem(SYSTEM_AUDIO_KEY) === "1";
    } catch {
      return false;
    }
  });
  const setSystemAudio = (on: boolean) => {
    setSystemAudioState(on);
    try {
      window.localStorage.setItem(SYSTEM_AUDIO_KEY, on ? "1" : "0");
    } catch {
      /* private mode */
    }
  };
  const [people, setPeople] = useState<People>("auto");
  const [hint, setHint] = useState("");
  /** The author edited the vocabulary: stop overwriting it with the
   *  workspace's. The hint is a suggestion about THIS meeting. */
  const hintTouched = useRef(false);
  const [showOptions, setShowOptions] = useState(false);
  const [showContext, setShowContext] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const scratch = useRef<HTMLTextAreaElement>(null);

  // The workspace's own names and terms, so the transcriber has the
  // spellings before it guesses (Sprint 35). Pre-filled, never forced.
  useEffect(() => {
    let cancelled = false;
    void glossaryHint()
      .then(({ hint: text }) => {
        if (!cancelled && text && !hintTouched.current) setHint(text);
      })
      .catch(() => {
        /* no glossary yet, or the service is down: the field stays empty */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const startedAt = useRef(0);
  const elapsedMs = useCallback(
    () => (startedAt.current ? Date.now() - startedAt.current : 0),
    [],
  );
  const note = useMeetingNote(elapsedMs);

  const { captures, noteErrors, createNote, cancel, refresh } = useCaptures({
    // A job bound to a live meeting note finishes into THAT note.
    meetingNotes: note.noteId && jobId ? { [jobId]: note.noteId } : undefined,
    onNoteReady: (jid, noteId) => {
      if (jid === jobId) navigate(`/notes/${noteId}`, { replace: true });
    },
  });

  // Latest submit settings, readable from the recorder's onstop closure.
  const settings = useRef({ title, language, diarize, hint, people, eventCtx, displayName });
  settings.current = { title, language, diarize, hint, people, eventCtx, displayName };

  const submit = useCallback(
    async (audio: RecordedAudio, captureSource: CaptureSource) => {
      const s = settings.current;
      const twoChannel = audio.channelLayout === "mic_system";
      setPhase("uploading");
      try {
        // A 2-channel capture the server cannot read as one is re-posted
        // once as mono — the recording matters more than the split.
        const { job, fellBackToMono } = await submitWithLayoutFallback(submitJob, {
          audio: audio.blob,
          filename: audio.filename,
          language: s.language,
          diarize: s.diarize,
          vocabularyHint: s.hint,
          speakersExpected: s.diarize && typeof s.people === "number" ? s.people : undefined,
          // Both go when set; a "People" number wins on the server.
          ...(s.diarize ? contextFields(s.eventCtx) : {}),
          captureSource,
          // Sprint F1: absent for an uploaded file — nobody pressed Record.
          ...(audio.recordPressedAt ? { recordPressedAt: audio.recordPressedAt } : {}),
          ...(audio.firstFrameOffsetMs != null ? { firstFrameOffsetMs: audio.firstFrameOffsetMs } : {}),
          ...(twoChannel
            ? { channelLayout: "mic_system" as const, localSpeakerName: s.displayName }
            : {}),
        });
        if (fellBackToMono) {
          toast.info("Recorded as a single channel — the tab audio could not be separated.");
        }
        rememberTitle(job.id, s.title);
        markMine(job.id);
        setJobId(job.id);
        setPhase("processing");
        // Bind the recording to the note the author has been typing in.
        // Also creates the note when `start` could not (offline at Record).
        await note.attachJob(job.id);
        void refresh();
      } catch (err) {
        toast.error(messageFor(err));
        setPhase("idle");
      }
    },
    [refresh, toast, note],
  );

  const onRecordError = useCallback((msg: string) => toast.error(msg), [toast]);
  const submitRecording = useCallback(
    (audio: RecordedAudio) =>
      void submit(audio, settings.current.eventCtx ? "calendar_event" : "manual"),
    [submit],
  );
  const onSystemAudioUnavailable = useCallback(
    () => toast.info("Recording the microphone only — the browser offered no tab audio."),
    [toast],
  );
  const rec = useRecorder(submitRecording, onRecordError, {
    systemAudio,
    onSystemAudioUnavailable,
  });

  /**
   * Record. The recorder starts FIRST and the note is opened beside it:
   * a note we failed to create is recoverable at Stop, a meeting we failed
   * to record is not.
   */
  const onRecord = async () => {
    startedAt.current = Date.now();
    await rec.start();
    void note.start({
      title: settings.current.title,
      language,
      meetingType,
      calendar: meetingCalendar(eventCtx),
    });
    // The scratchpad is where the value is: put the caret there.
    window.setTimeout(() => scratch.current?.focus(), 0);
  };

  const onStop = () => {
    void note.save();
    rec.stop();
  };

  // Don't let a tab close eat a recording — or unsaved scratch text.
  useEffect(() => {
    if (!rec.recording && phase !== "uploading" && !note.hasUnsaved()) return;
    const onUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, [rec.recording, phase, note]);

  const onFile = (file: File | undefined | null) => {
    if (!file) return;
    // An uploaded file is always sent as it is: no channel layout is declared.
    void submit({ blob: file, filename: file.name, channelLayout: "mono" }, "upload");
  };

  const job = jobId ? (captures?.find((c) => c.job.id === jobId)?.job ?? null) : null;
  const uploadFirst = params.get("mode") === "upload";
  const live = rec.recording || phase !== "idle";

  // ── the scratchpad ──────────────────────────────────────────────────

  const scratchpad = (
    <div className="scratchpad">
      <input
        className="title-input"
        placeholder="Untitled meeting"
        aria-label="Meeting title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <textarea
        ref={scratch}
        className="textarea seamless scratch-area"
        aria-label="My notes"
        placeholder="Type what matters. We'll fill in the rest."
        value={note.myNotes}
        onChange={(e) => note.onType(e.target.value)}
      />
      <p className="help scratch-status" role="status" aria-live="polite">
        {note.saving
          ? "Saving…"
          : note.noteId
            ? "Saved to this note — open on any device."
            : "Kept in this tab until the note opens."}
      </p>
      {eventCtx && (eventCtx.attendees.length > 0 || eventCtx.agenda.length > 0) && (
        <div className="scratch-context">
          <button
            className="disclosure"
            aria-expanded={showContext}
            onClick={() => setShowContext((v) => !v)}
          >
            From the invite
          </button>
          {showContext && (
            <div className="scratch-context-body">
              {eventCtx.attendees.length > 0 && (
                <p className="help">{eventCtx.attendees.join(", ")}</p>
              )}
              {eventCtx.agenda.length > 0 && (
                <ul className="help">
                  {eventCtx.agenda.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );

  // ── live: recording, uploading, transcribing ────────────────────────

  if (live) {
    const detected = languageName(job?.detected_language);
    const failed = job?.status === "failed";
    const cancelled = job?.status === "cancelled";
    const noteError = job && job.status === "complete" ? noteErrors[job.id] : undefined;
    const status = rec.recording
      ? "Recording — type anything worth remembering."
      : phase === "uploading"
        ? "Uploading the recording…"
        : job?.status === "complete"
          ? `Writing your notes${detected ? ` in ${detected}` : ""}…`
          : job?.status === "running"
            ? "Transcribing… this takes about as long as the recording"
            : "Waiting for a transcription slot…";

    return (
      <div className="meeting meeting-live">
        <div className="recorder-bar" role="group" aria-label="Recording">
          <div className={`level-meter sm ${rec.recording ? "live" : ""}`} aria-hidden="true">
            {rec.levels.map((lvl, i) => (
              <span
                key={i}
                className="bar"
                style={{
                  height: rec.recording ? Math.max(3, Math.round(lvl * 24)) : 3 + ((i * 7) % 7),
                }}
              />
            ))}
          </div>
          {rec.recording ? (
            <>
              <div className="rec-timer sm">
                <span className="rec-pulse" aria-hidden="true" />
                <span aria-live="off">
                  {rec.firstFrameOffsetMs == null ? "Starting…" : formatElapsed(rec.elapsedMs)}
                </span>
                {/* Sprint F1: what the recording will not hold, said while it
                    still matters. Under a second is ordinary; not shown. */}
                {rec.firstFrameOffsetMs != null && rec.firstFrameOffsetMs >= 1000 && (
                  <span className="help rec-latency">
                    Recording from {formatOffset(rec.firstFrameOffsetMs)}
                  </span>
                )}
              </div>
              <button className="btn rec" onClick={onStop}>
                <StopIcon size={13} /> Stop
              </button>
            </>
          ) : (
            <>
              {!failed && !cancelled && !noteError && (
                <span className="stage-pulse sm" aria-hidden="true" />
              )}
              <span className="rec-status" role="status" aria-live="polite">
                {failed || cancelled
                  ? (job?.error_message ??
                    (cancelled ? "Transcription cancelled" : "Transcription failed"))
                  : (noteError ?? status)}
              </span>
              {job && (job.status === "queued" || job.status === "running") && (
                <button
                  className="btn ghost sm"
                  onClick={() => void cancel(job).catch((err) => toast.error(messageFor(err)))}
                >
                  Cancel
                </button>
              )}
              {noteError && job && (
                <button
                  className="btn primary sm"
                  onClick={() =>
                    void createNote(job).catch((err) => toast.error(messageFor(err)))
                  }
                >
                  Try again
                </button>
              )}
              {(failed || cancelled) && (
                <button
                  className="btn sm"
                  onClick={() => {
                    setJobId(null);
                    setPhase("idle");
                    note.reset();
                  }}
                >
                  Try again
                </button>
              )}
            </>
          )}
          <span className="grow" />
          <Link to="/" className="btn ghost sm">
            Notes
          </Link>
        </div>
        {scratchpad}
        {rec.recording && (
          <p className="help meeting-foot">
            Everything you type is in the note already. Stopping uploads the recording and fills
            in the rest.
          </p>
        )}
      </div>
    );
  }

  // ── idle ────────────────────────────────────────────────────────────

  return (
    <div
      className={`meeting ${drag ? "drag" : ""}`}
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
      {firstRun && (
        <div className="banner banner-info first-run" role="status">
          <span className="grow">
            Record or upload your first meeting — your notes will be ready to share in minutes.
          </span>
          <button className="btn ghost sm" onClick={dismissFirstRun}>
            Got it
          </button>
        </div>
      )}
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
      {eventCtx && eventCtx.attendee_count > 0 && (
        <p className="help meeting-context">
          {eventCtx.attendee_count} invited
          {eventCtx.attendees.length > 0 && " · names will be offered for speakers"}
          {eventCtx.agenda.length > 0 && ` · ${eventCtx.agenda.length} agenda points`}
        </p>
      )}

      <div className="seg chips" role="group" aria-label="Meeting type">
        {MEETING_TYPES.map(([value, label]) => (
          <button
            key={value}
            type="button"
            className="seg-opt"
            aria-pressed={meetingType === value}
            onClick={() => setMeetingType(value)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="meeting-stage idle">
        <div className="level-meter" aria-hidden="true">
          {rec.levels.map((_lvl, i) => (
            <span key={i} className="bar" style={{ height: 3 + ((i * 7) % 9) }} />
          ))}
        </div>
        <button className="btn accent lg rec-start" onClick={() => void onRecord()} autoFocus={uploadFirst}>
          <MicIcon size={16} /> Record
        </button>
        <p className="help">
          The note opens as you press Record — type in it while the meeting runs. Or{" "}
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
      </div>

      <div className="meeting-options">
        <button
          className="disclosure"
          aria-expanded={showOptions}
          onClick={() => setShowOptions((v) => !v)}
        >
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
                Detect listens to the recording and writes the transcript and note in that
                language.
              </span>
            </div>
            <label className="chk-row">
              <input
                type="checkbox"
                className="chk"
                checked={diarize}
                onChange={(e) => setDiarize(e.target.checked)}
              />
              Tell speakers apart
            </label>
            <label className="chk-row">
              <input
                type="checkbox"
                className="chk"
                checked={systemAudio}
                onChange={(e) => setSystemAudio(e.target.checked)}
              />
              Also record this tab&apos;s audio (Me / Them)
            </label>
            <div className="field">
              <span className="label">People</span>
              <div className="seg" role="group" aria-label="People in the meeting">
                {PEOPLE.map(([value, label]) => (
                  <button
                    key={label}
                    type="button"
                    className="seg-opt"
                    aria-pressed={people === value}
                    disabled={!diarize}
                    onClick={() => setPeople(value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <span className="help">
                {diarize ? "Auto counts the voices itself." : "Turn on “Tell speakers apart” to set this."}
              </span>
            </div>
            <div className="field">
              <span className="label">Words to listen for</span>
              <input
                className="input"
                placeholder="Names, product terms, acronyms…"
                maxLength={2000}
                value={hint}
                onChange={(e) => {
                  hintTouched.current = true;
                  setHint(e.target.value);
                }}
              />
              <span className="help">
                Pre-filled from your workspace&apos;s names and terms. Editing it changes this
                meeting only.
              </span>
            </div>
          </div>
        )}
      </div>

      {drag && (
        <div className="meeting-drop" aria-hidden="true">
          <UploadIcon size={22} /> Drop to transcribe
        </div>
      )}
    </div>
  );
}
