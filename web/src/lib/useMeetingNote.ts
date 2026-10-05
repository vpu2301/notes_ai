// Client half of a live capture: open the note at Record, autosave `user_notes`,
// collect line timings, attach job then transcript.
// Rule: NOTHING here may stop or delay the recording; `start()` is fire-and-forget.

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/http";
import {
  attachJob as apiAttachJob,
  attachTranscript as apiAttachTranscript,
  getNote,
  putLineTimes,
  startMeeting,
  updateDraft,
} from "../api/notes";
import type {
  MeetingCalendarContext,
  MeetingType,
  NoteContent,
  StartMeetingRequest,
} from "../api/types";
import { LineTimeQueue, mergeScratch } from "./myNotes";

/** Where the author's own lines live in every meeting template. */
export const USER_NOTES_SECTION = "user_notes";

const AUTOSAVE_MS = 900;

function sectionText(content: NoteContent | null, key: string): string {
  return content?.sections?.find((s) => s.section_key === key)?.text ?? "";
}

function withSection(content: NoteContent, key: string, text: string): NoteContent {
  const sections = content.sections ?? [];
  const found = sections.some((s) => s.section_key === key);
  return {
    ...content,
    sections: found
      ? sections.map((s) => (s.section_key === key ? { ...s, text } : s))
      : [...sections, { section_key: key, text }],
  };
}

export interface StartArgs {
  title: string;
  language: StartMeetingRequest["language"];
  meetingType: MeetingType;
  calendar?: MeetingCalendarContext;
}

/**
 * @param elapsedMs the recording clock, in milliseconds since t=0.
 */
export function useMeetingNote(elapsedMs: () => number) {
  const [noteId, setNoteId] = useState<string | null>(null);
  /** What the author has typed. Owned here so the textarea stays instant. */
  const [myNotes, setMyNotes] = useState("");
  const [saving, setSaving] = useState(false);
  /** The note could not be opened; the page creates one at stop instead. */
  const [pendingStart, setPendingStart] = useState<StartArgs | null>(null);

  const captureId = useRef<string>(crypto.randomUUID());
  // The id as of NOW: `attachJob` may open and save before React re-renders.
  const id = useRef<string | null>(null);
  const content = useRef<NoteContent | null>(null);
  const version = useRef(0);
  const dirty = useRef(false);
  const timer = useRef<number | null>(null);
  const queue = useRef(new LineTimeQueue(elapsedMs));
  // Latest text, readable from the save closure without re-arming it.
  const text = useRef("");
  text.current = myNotes;

  const load = useCallback(async (id: string) => {
    const env = await getNote(id);
    const remote = env.content;
    if (!remote) return;
    content.current = remote;
    version.current = env.current_version_number;
    // Another device may have typed here: append, never overwrite.
    setMyNotes((local) => mergeScratch(sectionText(remote, USER_NOTES_SECTION), local));
  }, []);

  /** Open the note. Never throws — a failure is remembered, not raised. */
  const start = useCallback(
    async (args: StartArgs) => {
      try {
        const res = await startMeeting({
          client_capture_id: captureId.current,
          title: args.title || undefined,
          started_at: new Date().toISOString(),
          language: args.language,
          meeting_type: args.meetingType,
          calendar: args.calendar,
        });
        id.current = res.id;
        setNoteId(res.id);
        setPendingStart(null);
        await load(res.id);
        return res.id;
      } catch {
        // Offline or service down; the meeting matters more.
        setPendingStart(args);
        return null;
      }
    },
    [load],
  );

  const flush = useCallback(async () => {
    const noteId = id.current;
    const base = content.current;
    if (!noteId || !base || !dirty.current) return;
    dirty.current = false;
    const next = withSection(base, USER_NOTES_SECTION, text.current);
    // Keying is async: a line typed just before the debounce must go with this save.
    await queue.current.settled();
    const lines = queue.current.drain();
    setSaving(true);
    try {
      const res = await updateDraft(noteId, next, version.current);
      content.current = next;
      version.current = res.version_number;
    } catch (err) {
      dirty.current = true;
      // Conflict = another device wrote: re-read and merge. Else retry on next keystroke.
      if (err instanceof ApiError && err.isConflict) await load(noteId).catch(() => {});
    } finally {
      setSaving(false);
    }
    if (lines.length > 0) {
      // Timings are a hint: requeue on failure; the line still anchors lexically.
      await putLineTimes(noteId, lines).catch(() => queue.current.requeue(lines));
    }
  }, [load]);

  // The debounce timer must always reach the CURRENT flush.
  const flushRef = useRef(flush);
  flushRef.current = flush;

  /** Call on every change of the scratchpad. */
  const onType = useCallback((next: string) => {
    setMyNotes(next);
    dirty.current = true;
    void queue.current.observe(next);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void flushRef.current(), AUTOSAVE_MS);
  }, []);

  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );

  /** Save now — at Stop, and when the tab is going away. */
  const save = useCallback(async () => {
    if (timer.current) window.clearTimeout(timer.current);
    await flushRef.current();
  }, []);

  /** The recording reached asr-service. Creates the note first if `start` could not. */
  const attachJob = useCallback(
    async (jobId: string) => {
      if (!id.current && pendingStart) await start(pendingStart);
      const noteId = id.current;
      if (!noteId) return null;
      await save();
      await apiAttachJob(noteId, jobId).catch(() => {});
      return noteId;
    },
    [pendingStart, start, save],
  );

  const attachTranscript = useCallback(async (id: string) => {
    await apiAttachTranscript(id);
  }, []);

  const reset = useCallback(() => {
    captureId.current = crypto.randomUUID();
    id.current = null;
    content.current = null;
    version.current = 0;
    dirty.current = false;
    queue.current = new LineTimeQueue(elapsedMs);
    setNoteId(null);
    setMyNotes("");
    setPendingStart(null);
  }, [elapsedMs]);

  return {
    noteId,
    myNotes,
    onType,
    saving,
    /** Unsaved typing; read at the tab-close guard, not at render. */
    hasUnsaved: () => dirty.current || queue.current.size > 0,
    start,
    save,
    attachJob,
    attachTranscript,
    reset,
  };
}
