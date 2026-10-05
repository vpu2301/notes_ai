import type { CSSProperties } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { getJob, rediarize, resetSpeakerEdits, setSpeakerNames, undoRediarize } from "../api/asr";
import { ApiError } from "../api/http";
import { messageFor } from "../lib/errorCopy";
import type { DiarizationStatus, NameSuggestion, SpeakerNameSource, SpeakerSide, SpeakerStat } from "../api/types";
import { defaultSpeakerName } from "../api/types";
import { speakerInitials, speakerTint } from "../lib/speakers";
import { useDismiss } from "../lib/useDismiss";
import { ConfirmDialog } from "./ConfirmDialog";
import { CloseIcon, MicIcon, SpeakerIcon } from "./icons";
import { Menu, type MenuItem } from "./Menu";
import { NameSuggestionChip } from "./NameSuggestionChip";
import { copyText } from "../i18n/speakers";

const POLL_MS = 3000;
const MAX_SPEAKERS = 8;

/** A speaker this small is probably someone else split off (or a cough). */
export function isSmallSpeaker(s: SpeakerStat): boolean {
  return s.share < 0.05 || s.speech_ms < 15_000;
}

function spoke(ms: number): string {
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s} s` : `${Math.round(s / 60)} min`;
}

function keptKey(jobId: string): string {
  return `speaker-keep:${jobId}`;
}

function readKept(jobId: string): string[] {
  try {
    return JSON.parse(sessionStorage.getItem(keptKey(jobId)) ?? "[]") as string[];
  } catch {
    return [];
  }
}

function relabelLaterKey(jobId: string): string {
  return `relabel-later:${jobId}`;
}

function readRelabelLater(jobId: string): boolean {
  try {
    return sessionStorage.getItem(relabelLaterKey(jobId)) === "1";
  } catch {
    return false;
  }
}

function countOkKey(jobId: string): string {
  return `speaker-count-ok:${jobId}`;
}

function readCountOk(jobId: string): boolean {
  try {
    return localStorage.getItem(countOkKey(jobId)) === "1";
  } catch {
    return false;
  }
}

/** Where a speaker was heard, in words (two-channel captures only). */
export const SIDE_COPY: Record<SpeakerSide, string> = {
  local: "On your microphone",
  remote: "On the call audio",
};

function SideGlyph({ side }: { side: SpeakerSide }) {
  return (
    <span className={`speaker-side ${side}`} role="img" aria-label={SIDE_COPY[side]} title={SIDE_COPY[side]}>
      {side === "local" ? <MicIcon size={12} /> : <SpeakerIcon size={12} />}
    </span>
  );
}

/**
 * The custom names to keep when one label's name is removed: every other
 * name as it is, that label back to its "Speaker N" default.
 */
export function namesWithout(names: Record<string, string>, label: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [l, n] of Object.entries(names)) {
    if (l !== label && n && n !== defaultSpeakerName(l)) out[l] = n;
  }
  return out;
}

function speakersLabel(n: number): string {
  return n === 1 ? "1 speaker" : `${n} speakers`;
}

function inProgress(status: DiarizationStatus | null | undefined): boolean {
  return status === "queued" || status === "running";
}

/** The re-run's refusals, in a sentence; anything else keeps the server's own. */
const RELABEL_COPY: Record<string, string> = {
  job_not_complete: "The transcript isn't finished yet — try again when it is.",
  rediarize_in_progress: "Speakers are already being re-labelled.",
  audio_unavailable: "The recording is no longer kept, so speakers can't be re-labelled.",
  rediarize_limit: "This transcript has been re-labelled as often as it can be.",
  rate_limited: "Too many re-runs in the last hour. Try again later.",
  enqueue_failed: "Couldn't start re-labelling. Nothing changed — try again in a moment.",
  nothing_to_undo: "There's nothing to undo any more.",
};

export function relabelError(err: unknown): string {
  if (err instanceof ApiError && err.code && RELABEL_COPY[err.code]) return RELABEL_COPY[err.code]!;
  return messageFor(err);
}

/**
 * The speakers of a diarized transcript: one chip per speaker with its talk
 * share, a menu to rename or merge it, and — when a speaker barely spoke —
 * one question: is this the same person as someone else?
 */
export function SpeakerRoster({
  jobId,
  speakers,
  names,
  stats,
  busy,
  undo,
  countConfidence = null,
  speakersHint = null,
  mergeCount = 0,
  sides = {},
  nameSources = {},
  suggestions = [],
  relabelAvailable = false,
  onAcceptSuggestion,
  onDismissSuggestion,
  onShowSuggestion,
  onNameCleared,
  onRename,
  onMerge,
  onRelabelled,
  onRelabelRunning,
  onReset,
}: {
  jobId: string;
  speakers: string[];
  names: Record<string, string>;
  stats: SpeakerStat[];
  busy: boolean;
  /**
   * The last edit, while it can still be undone: a merge names its target
   * (`into`), a moved turn says what moved (`message`).
   */
  undo: { into?: string; message?: string; onUndo: () => void } | null;
  /** The diarizer's own doubt about the count ("low" asks the person). */
  countConfidence?: "high" | "low" | null;
  /** The count a person asked for on this labelling. */
  speakersHint?: number | null;
  /** Live speaker edits (merges and moved turns) — a re-run replaces them. */
  mergeCount?: number;
  /** Microphone or call audio per label (Sprint 31); empty for mono jobs. */
  sides?: Record<string, SpeakerSide>;
  /** How each name was chosen; a `channel` name can be removed from its chip. */
  nameSources?: Record<string, SpeakerNameSource>;
  /** Who speakers probably are (Sprint 32) — already filtered to the open ones. */
  suggestions?: NameSuggestion[];
  /** The labelling is from an older engine and the audio is kept: offer a re-label. */
  relabelAvailable?: boolean;
  onAcceptSuggestion?: (s: NameSuggestion) => void;
  onDismissSuggestion?: (s: NameSuggestion) => void;
  /** The suggestion's quote was clicked: show its turn. */
  onShowSuggestion?: (s: NameSuggestion) => void;
  /** A channel-given name was removed; `speakerNames` is the server's mapping. */
  onNameCleared?: (label: string, speakerNames: Record<string, string>) => void;
  onRename: (label: string) => void;
  onMerge: (from: string, into: string) => void;
  /** Speakers were re-labelled (or the re-run undone): reload the transcript. */
  onRelabelled?: (kind: "rerun" | "undo") => Promise<void> | void;
  /** A re-label is queued or running — turn edits wait for it. */
  onRelabelRunning?: (running: boolean) => void;
  /** Every speaker edit was reset: reload the transcript. */
  onReset?: () => Promise<void> | void;
}) {
  const [kept, setKept] = useState<string[]>(() => readKept(jobId));
  const [countOk, setCountOk] = useState(() => readCountOk(jobId));
  const relabel = useRelabel(jobId, onRelabelled);
  const [relabelLater, setRelabelLater] = useState(() => readRelabelLater(jobId));
  const [picking, setPicking] = useState(false);
  const [resetting, setResetting] = useState<{ busy: boolean; error: string | null } | null>(null);
  const [clearing, setClearing] = useState<{ label: string | null; error: string | null }>({
    label: null,
    error: null,
  });
  const online = useOnline();
  const name = (label: string) => names[label] ?? defaultSpeakerName(label);
  const byLabel = new Map(stats.map((s) => [s.label, s]));
  const largest = [...stats].sort((a, b) => b.speech_ms - a.speech_ms);

  // One question at a time: an offer to re-label with the current engine
  // outranks doubt about the count, which outranks "is this small speaker
  // someone else?", and a re-run in flight asks nothing.
  const offerRelabel =
    relabelAvailable && !relabelLater && !relabel.running && !relabel.working && relabel.outcome !== "done";
  const askCount = countConfidence === "low" && !countOk && !relabel.running && !offerRelabel;
  const candidate =
    speakers.length > 1 && !askCount && !relabel.running && !offerRelabel
      ? largest.find((s) => isSmallSpeaker(s) && !kept.includes(s.label) && speakers.includes(s.label))
      : undefined;
  const targets = candidate ? largest.filter((s) => s.label !== candidate.label).slice(0, 2) : [];

  const keep = (label: string) => {
    const next = [...kept, label];
    setKept(next);
    try {
      sessionStorage.setItem(keptKey(jobId), JSON.stringify(next));
    } catch {
      /* private mode: remembered for this view only */
    }
  };

  const countIsFine = () => {
    setCountOk(true);
    try {
      localStorage.setItem(countOkKey(jobId), "1");
    } catch {
      /* private mode: remembered for this view only */
    }
  };

  const notNow = () => {
    setRelabelLater(true);
    try {
      sessionStorage.setItem(relabelLaterKey(jobId), "1");
    } catch {
      /* private mode: remembered for this view only */
    }
  };

  const locked = busy || relabel.running || relabel.working || clearing.label !== null;

  // "· from your microphone" ✕: the name goes, every other name stays.
  const clearName = async (label: string) => {
    const from = name(label);
    setClearing({ label, error: null });
    try {
      const res = await setSpeakerNames(jobId, namesWithout(names, label));
      setClearing({ label: null, error: null });
      onNameCleared?.(label, res.speaker_names);
    } catch (err) {
      setClearing({ label: null, error: `Couldn't remove ${from}: ${messageFor(err)}` });
    }
  };

  const running = relabel.running;
  const reportRunning = useRef(onRelabelRunning);
  reportRunning.current = onRelabelRunning;
  useEffect(() => {
    reportRunning.current?.(running);
  }, [running]);

  const confirmReset = async () => {
    setResetting({ busy: true, error: null });
    try {
      await resetSpeakerEdits(jobId);
      setResetting(null);
      await onReset?.();
    } catch (err) {
      setResetting({ busy: false, error: messageFor(err) });
    }
  };

  return (
    <div className="speaker-roster">
      {relabel.running && (
        <div className="banner banner-info speaker-prompt" role="status">
          <span className="grow">Re-labelling speakers… the transcript stays readable</span>
        </div>
      )}
      {relabel.outcome === "failed" && (
        <div className="banner banner-warn speaker-prompt" role="alert">
          <span className="grow">Couldn't re-label speakers</span>
          <button className="btn sm" disabled={relabel.working || !online} onClick={() => void relabel.retry()}>
            Try again
          </button>
        </div>
      )}
      {offerRelabel && (
        <div className="banner banner-info speaker-prompt" role="region" aria-label={copyText("relabelOfferAction")}>
          <span className="grow">{copyText("relabelOffer")}</span>
          <button
            className="btn sm"
            disabled={locked || !online}
            title={!online ? "Needs a connection" : undefined}
            onClick={() => void relabel.start(null)}
          >
            {copyText("relabelOfferAction")}
          </button>
          <button className="btn ghost sm" onClick={notNow}>
            {copyText("relabelOfferLater")}
          </button>
        </div>
      )}
      {askCount && (
        <div className="banner banner-info speaker-prompt" role="note">
          <span className="grow">We're not sure how many people spoke.</span>
          <button className="btn sm" disabled={locked || !online} onClick={() => setPicking(true)}>
            Set number
          </button>
          <button className="btn ghost sm" onClick={countIsFine}>
            Looks right
          </button>
        </div>
      )}
      {candidate && (
        <div className="banner banner-info speaker-prompt" role="note">
          <span className="grow">
            {name(candidate.label)} spoke for {spoke(candidate.speech_ms)}. Same person as someone else?
          </span>
          {targets.map((t) => (
            <button key={t.label} className="btn sm" disabled={locked} onClick={() => onMerge(candidate.label, t.label)}>
              {name(t.label)}
            </button>
          ))}
          <button className="btn ghost sm" onClick={() => keep(candidate.label)}>
            Keep
          </button>
        </div>
      )}
      {suggestions.length > 0 && onAcceptSuggestion && onDismissSuggestion && (
        <div className="name-suggestions">
          {suggestions.map((sg) => (
            <NameSuggestionChip
              key={`${sg.label}:${sg.name}`}
              suggestion={sg}
              speakerName={name(sg.label)}
              disabled={locked || !online}
              onAccept={onAcceptSuggestion}
              onDismiss={onDismissSuggestion}
              onShowQuote={onShowSuggestion}
            />
          ))}
        </div>
      )}
      {speakers.length > 0 && (
        <div className="speaker-chips">
          {speakers.map((label) => {
            const share = byLabel.get(label)?.share;
            // Earlier labels first: a merge keeps the lower number.
            const others = speakers.filter((l) => l !== label);
            const items: MenuItem[] = [
              { label: "Rename", onClick: () => onRename(label) },
              ...others.map((o, i) => ({
                label: `Merge into ${name(o)}`,
                onClick: () => onMerge(label, o),
                disabled: locked,
                sep: i === 0,
              })),
            ];
            const side = sides[label];
            const fromChannel = nameSources[label] === "channel" && names[label] !== undefined;
            const suggested =
              nameSources[label] === "suggestion" &&
              names[label] !== undefined &&
              names[label] !== defaultSpeakerName(label);
            const chip = (
              <Menu
                key={label}
                anchored
                label={copyText(suggested ? "chipMenuLabelSuggested" : "chipMenuLabel", { name: name(label) })}
                triggerClassName="speaker-chip"
                items={items}
                trigger={
                  <>
                    <span className="speaker-avatar sm" style={{ "--tint": speakerTint(name(label)) } as CSSProperties} aria-hidden="true">
                      {speakerInitials(name(label))}
                    </span>
                    {side && <SideGlyph side={side} />}
                    <span>{name(label)}</span>
                    {fromChannel && <span className="speaker-source">· from your microphone</span>}
                    {suggested && (
                      <span className="speaker-source speaker-suggested" title={copyText("suggestedMarkerLabel")}>
                        · {copyText("suggestedMarker")}
                      </span>
                    )}
                    {share !== undefined && <span className="speaker-share mono">{Math.round(share * 100)} %</span>}
                  </>
                }
              />
            );
            if (!fromChannel) return chip;
            return (
              <span key={label} className="speaker-chip-host">
                {chip}
                <button
                  type="button"
                  className="icon-btn speaker-chip-clear"
                  aria-label={copyText("removeChannelName", { name: name(label) })}
                  title={copyText("removeChannelName", { name: name(label) })}
                  disabled={locked || !online}
                  onClick={() => void clearName(label)}
                >
                  <CloseIcon size={12} />
                </button>
              </span>
            );
          })}
          <Menu
            anchored
            label="Speaker options"
            triggerClassName="icon-btn speaker-more"
            items={[
              {
                label: "Reset speaker edits",
                onClick: () => setResetting({ busy: false, error: null }),
                disabled: locked || !online || mergeCount === 0,
              },
            ]}
          />
        </div>
      )}
      {resetting && (
        <ConfirmDialog
          title="Reset speaker edits?"
          subtitle="All merges and moved turns in this transcript will be undone."
          confirmLabel="Reset"
          confirmDanger
          busy={resetting.busy}
          error={resetting.error}
          onConfirm={() => void confirmReset()}
          onCancel={() => setResetting(null)}
        />
      )}
      {undo && (
        <div className="speaker-undo" role="status">
          <span>{undo.message ?? (undo.into ? `Merged into ${name(undo.into)}` : "Speakers changed")}</span>
          <button className="btn ghost sm" onClick={undo.onUndo} disabled={busy}>
            Undo
          </button>
        </div>
      )}
      {relabel.outcome === "done" && (
        <div className="speaker-undo" role="status">
          <span>Now {speakersLabel(speakers.length)}</span>
          {relabel.canUndo && (
            <button className="btn ghost sm" onClick={() => void relabel.undo()} disabled={locked}>
              Undo
            </button>
          )}
        </div>
      )}
      {speakersHint != null && speakers.length < speakersHint && !relabel.running && (
        <span className="help">
          Only {speakers.length === 1 ? "1 voice" : `${speakers.length} voices`} could be told apart.
        </span>
      )}
      {clearing.error && (
        <span className="help speaker-error" role="alert">
          {clearing.error}
        </span>
      )}
      {relabel.error && (
        <span className="help speaker-error" role="alert">
          {relabel.error}
        </span>
      )}
      {speakers.length > 0 && (
        <SpeakerCountPicker
          open={picking}
          current={speakers.length}
          mergeCount={mergeCount}
          disabled={locked || !online}
          offline={!online}
          onOpen={() => setPicking(true)}
          onClose={() => setPicking(false)}
          onPick={(n) => {
            setPicking(false);
            void relabel.start(n);
          }}
        />
      )}
    </div>
  );
}

/**
 * "Wrong number of speakers?" — a count from 1 to 8, then one confirm that
 * says what a re-run costs (the merges made on the old labels).
 */
function SpeakerCountPicker({
  open,
  current,
  mergeCount,
  disabled,
  offline,
  onOpen,
  onClose,
  onPick,
}: {
  open: boolean;
  current: number;
  mergeCount: number;
  disabled: boolean;
  offline: boolean;
  onOpen: () => void;
  onClose: () => void;
  onPick: (count: number) => void;
}) {
  const [chosen, setChosen] = useState<number | null>(null);
  const close = useCallback(() => {
    setChosen(null);
    onClose();
  }, [onClose]);
  const ref = useDismiss<HTMLDivElement>(open, close);

  return (
    <div className="dropdown-host speaker-count" ref={ref}>
      <button
        type="button"
        className="link-btn"
        aria-haspopup="dialog"
        aria-expanded={open}
        disabled={disabled}
        title={offline ? "Needs a connection" : undefined}
        onClick={() => (open ? close() : onOpen())}
      >
        Wrong number of speakers?
      </button>
      {open && (
        <div className="dropdown left speaker-count-pop" role="dialog" aria-label="Number of speakers">
          <span className="label">How many people spoke?</span>
          <div className="seg wrap" role="group" aria-label="Number of speakers">
            {Array.from({ length: MAX_SPEAKERS }, (_, i) => i + 1).map((n) => (
              <button
                key={n}
                type="button"
                className="seg-opt"
                aria-pressed={chosen === n}
                onClick={() => setChosen(n)}
              >
                {n}
              </button>
            ))}
          </div>
          {chosen !== null && (
            <>
              <p className="help">
                {chosen === current
                  ? `Listen again for ${speakersLabel(chosen)}.`
                  : `Re-label the transcript as ${speakersLabel(chosen)}.`}
                {mergeCount > 0 &&
                  ` Your ${mergeCount === 1 ? "merge" : `${mergeCount} merges`} will be replaced by the new result.`}
              </p>
              <div className="speaker-count-actions">
                <button type="button" className="btn ghost sm" onClick={close}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn primary sm"
                  onClick={() => {
                    setChosen(null);
                    onPick(chosen);
                  }}
                >
                  Re-label
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/** The browser's idea of being online; speaker edits need a connection. */
export function useOnline(): boolean {
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine !== false));
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  return online;
}

/**
 * A speaker re-run, as the roster sees it: start it, poll the job every few
 * seconds while it is queued or running (also when the page opens on one
 * already in flight), reload the transcript when it lands, and undo it.
 */
function useRelabel(jobId: string, onRelabelled?: (kind: "rerun" | "undo") => Promise<void> | void) {
  const [status, setStatus] = useState<DiarizationStatus | null>(null);
  const [canUndo, setCanUndo] = useState(false);
  /** What this view saw a run end in — the failed strip and the "Now N" strip. */
  const [outcome, setOutcome] = useState<"done" | "failed" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  // Only a run this view watched reports its end; an old failure on the
  // job is history, not news.
  const watching = useRef(false);
  const lastCount = useRef<number | null>(null);
  const reload = useRef(onRelabelled);
  reload.current = onRelabelled;

  const refresh = useCallback(async () => {
    let job;
    try {
      job = await getJob(jobId);
    } catch {
      return; // transient — keep polling
    }
    const next = job.diarization_status ?? null;
    setCanUndo(job.can_undo_rediarize ?? false);
    if (inProgress(next)) watching.current = true;
    else if (watching.current && next === "complete") {
      watching.current = false;
      try {
        await reload.current?.("rerun");
      } catch (err) {
        setError(messageFor(err));
      }
      setOutcome("done");
    } else if (watching.current && next === "failed") {
      watching.current = false;
      setOutcome("failed");
    }
    setStatus(next);
  }, [jobId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const running = inProgress(status);
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(t);
  }, [running, refresh]);

  const start = async (count: number | null) => {
    setError(null);
    setOutcome(null);
    setWorking(true);
    lastCount.current = count;
    try {
      const res = await rediarize(jobId, count);
      watching.current = true;
      setStatus(res.diarization_status);
    } catch (err) {
      // Someone else's run is already going: watch that one instead.
      if (err instanceof ApiError && err.code === "rediarize_in_progress") {
        watching.current = true;
        setStatus("queued");
      } else {
        setError(relabelError(err));
      }
    } finally {
      setWorking(false);
    }
  };

  const undo = async () => {
    setError(null);
    setWorking(true);
    try {
      await undoRediarize(jobId);
      setOutcome(null);
      setCanUndo(false);
      await reload.current?.("undo");
    } catch (err) {
      setError(relabelError(err));
    } finally {
      setWorking(false);
    }
  };

  return {
    running,
    working,
    outcome,
    error,
    canUndo,
    start,
    retry: () => start(lastCount.current),
    undo,
  };
}
