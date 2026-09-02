import { useCallback, useEffect, useRef, useState } from "react";
import { cancelJob, listJobs } from "../api/asr";
import { ApiError } from "../api/http";
import { createFromTranscript, notesBySourceJob } from "../api/notes";
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
export function useCaptures(opts: { onNoteReady?: (jobId: string, noteId: string) => void } = {}) {
  const [jobs, setJobs] = useState<AsrJob[] | null>(null);
  const [links, setLinks] = useState<Record<string, string>>(loadLinks);
  const [creating, setCreating] = useState<Set<string>>(new Set());
  const onNoteReady = useRef(opts.onNoteReady);
  onNoteReady.current = opts.onNoteReady;

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
      try {
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
            rememberLink(job.id, l.note_id);
            setLinks(loadLinks());
            onNoteReady.current?.(job.id, l.note_id);
            return l.note_id;
          }
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

  // Auto-convert: finished jobs this browser recorded become notes on their own.
  useEffect(() => {
    if (!jobs) return;
    for (const job of jobs) {
      if (job.status !== "complete" || links[job.id] || !isMine(job.id) || autoAttempted.has(job.id)) continue;
      autoAttempted.add(job.id);
      void createNote(job).catch(() => autoAttempted.delete(job.id));
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

  return { captures, links, creating, refresh, createNote, cancel, dismissFailed };
}
