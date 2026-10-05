import { useCallback, useEffect, useRef, useState } from "react";
import { cancelJob, listJobs } from "../api/asr";
import { ApiError } from "../api/http";
import { messageFor } from "./errorCopy";
import { attachTranscript, createFromTranscript, notesBySourceJob } from "../api/notes";
import type { AsrJob } from "../api/types";
import { dismiss, isDismissed, isMine, loadLinks, loadTitles, rememberLink } from "./captures";

const POLL_MS = 3000;

/** A transcription that has not become a note yet (or failed trying). */
export interface Capture {
  job: AsrJob;
  title: string;
  /** This browser started it, so a note is made for it automatically. */
  mine: boolean;
}

// Survives route changes: a job is only ever auto-converted once per session.
const autoAttempted = new Set<string>();

/**
 * The meeting pipeline, as the UI sees it: recent transcription jobs, the
 * notes they turned into, and automatic note creation for the jobs this
 * browser recorded. Polls while anything is still processing.
 */
export function useCaptures(
  opts: {
    onNoteReady?: (jobId: string, noteId: string) => void;
    /** Jobs whose note was opened at Record: finish with `attachTranscript`, not `from-transcript` (409). */
    meetingNotes?: Record<string, string>;
  } = {},
) {
  const [jobs, setJobs] = useState<AsrJob[] | null>(null);
  const [links, setLinks] = useState<Record<string, string>>(loadLinks);
  const [creating, setCreating] = useState<Set<string>>(new Set());
  /** Why the last note write for a job failed; shown with a retry. */
  const [noteErrors, setNoteErrors] = useState<Record<string, string>>({});
  const onNoteReady = useRef(opts.onNoteReady);
  onNoteReady.current = opts.onNoteReady;
  const meetingNotes = useRef(opts.meetingNotes);
  meetingNotes.current = opts.meetingNotes;

  const refresh = useCallback(async () => {
    let list: AsrJob[];
    try {
      list = await listJobs();
    } catch {
      return; // transient — keep what we have
    }
    const known = loadLinks();
    const unresolved = list.filter((j) => j.status === "complete" && !known[j.id]).map((j) => j.id);
    if (unresolved.length > 0) {
      try {
        for (const l of await notesBySourceJob(unresolved)) rememberLink(l.asr_job_id, l.note_id);
      } catch {
        /* the note service may be down; try again next poll */
      }
    }
    setLinks(loadLinks());
    setJobs(list);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const busy = jobs?.some((j) => j.status === "queued" || j.status === "running") ?? false;
  useEffect(() => {
    if (!busy) return;
    const t = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(t);
  }, [busy, refresh]);

  const createNote = useCallback(
    async (job: AsrJob, templateId?: string) => {
      setCreating((s) => new Set(s).add(job.id));
      setNoteErrors((e) => {
        if (!(job.id in e)) return e;
        const { [job.id]: _gone, ...rest } = e;
        return rest;
      });
      try {
        // The note may already exist (typed in since Record): attach, do not create.
        const live = meetingNotes.current?.[job.id];
        if (live) {
          try {
            await attachTranscript(live);
            rememberLink(job.id, live);
            setLinks(loadLinks());
            onNoteReady.current?.(job.id, live);
            return live;
          } catch (err) {
            // Live note binned mid-meeting: the recording gets a fresh note below.
            if (!(err instanceof ApiError && err.status === 404)) throw err;
          }
        }
        const res = await createFromTranscript({
          asr_job_id: job.id,
          template_id: templateId,
          title: loadTitles()[job.id] || undefined,
        });
        rememberLink(job.id, res.id);
        setLinks(loadLinks());
        onNoteReady.current?.(job.id, res.id);
        return res.id;
      } catch (err) {
        // Someone (another tab, the desktop app) already made the note.
        if (err instanceof ApiError && err.status === 409) {
          const [l] = await notesBySourceJob([job.id]).catch(() => []);
          if (l) {
            // Meeting note opened elsewhere (the phone); finishing is idempotent.
            await attachTranscript(l.note_id).catch(() => {});
            rememberLink(job.id, l.note_id);
            setLinks(loadLinks());
            onNoteReady.current?.(job.id, l.note_id);
            return l.note_id;
          }
        }
        // 401 signs out via http.ts; anything else must be visible.
        if (!(err instanceof ApiError && err.status === 401)) {
          setNoteErrors((e) => ({ ...e, [job.id]: messageFor(err) }));
        }
        throw err;
      } finally {
        setCreating((s) => {
          const n = new Set(s);
          n.delete(job.id);
          return n;
        });
      }
    },
    [],
  );

  // Auto-convert finished jobs this browser recorded (also ones whose note is already open).
  useEffect(() => {
    if (!jobs) return;
    for (const job of jobs) {
      if (job.status !== "complete" || !isMine(job.id) || autoAttempted.has(job.id)) continue;
      const live = meetingNotes.current?.[job.id];
      if (links[job.id] && !live) continue;
      autoAttempted.add(job.id);
      // One automatic try; afterwards the user retries from the page.
      void createNote(job).catch(() => {});
    }
  }, [jobs, links, createNote]);

  const cancel = useCallback(
    async (job: AsrJob) => {
      await cancelJob(job.id);
      await refresh();
    },
    [refresh],
  );

  const dismissFailed = useCallback((job: AsrJob) => {
    dismiss(job.id);
    setJobs((prev) => prev?.filter((j) => j.id !== job.id) ?? null);
  }, []);

  const titles = loadTitles();
  const captures: Capture[] | null =
    jobs?.flatMap((job) => {
      const mine = isMine(job.id);
      const pending = job.status === "queued" || job.status === "running";
      const readyUnlinked = job.status === "complete" && !links[job.id];
      const failedMine = job.status === "failed" && mine && !isDismissed(job.id);
      if (!pending && !readyUnlinked && !failedMine) return [];
      return [{ job, title: titles[job.id] ?? "", mine }];
    }) ?? null;

  return { captures, links, creating, noteErrors, refresh, createNote, cancel, dismissFailed };
}
