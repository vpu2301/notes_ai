// Per-browser bookkeeping for meeting captures. The backend knows jobs and
// notes; the browser remembers which jobs IT started (so only those get a
// note made automatically), the title typed before recording, and the
// job → note links it has already resolved.

const TITLES = "notesai.capture.titles";
const MINE = "notesai.capture.mine";
const LINKS = "notesai.capture.links";
const DISMISSED = "notesai.capture.dismissed";

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode / quota — bookkeeping is best-effort */
  }
}

// ── titles ────────────────────────────────────────────────────────────

export function loadTitles(): Record<string, string> {
  return read<Record<string, string>>(TITLES, {});
}

export function rememberTitle(jobId: string, title: string): void {
  const all = loadTitles();
  if (title.trim()) all[jobId] = title.trim();
  else delete all[jobId];
  write(TITLES, all);
}

// ── "mine" — jobs this browser submitted ──────────────────────────────

export function markMine(jobId: string): void {
  const all = read<string[]>(MINE, []);
  if (!all.includes(jobId)) write(MINE, [...all, jobId].slice(-200));
}

export function isMine(jobId: string): boolean {
  return read<string[]>(MINE, []).includes(jobId);
}

// ── job → note links ──────────────────────────────────────────────────

export function loadLinks(): Record<string, string> {
  return read<Record<string, string>>(LINKS, {});
}

export function rememberLink(jobId: string, noteId: string): void {
  const all = loadLinks();
  all[jobId] = noteId;
  write(LINKS, all);
}

export function jobForNote(noteId: string): string | null {
  const all = loadLinks();
  for (const [jobId, nid] of Object.entries(all)) {
    if (nid === noteId) return jobId;
  }
  return null;
}

// ── dismissed failures ────────────────────────────────────────────────

export function dismiss(jobId: string): void {
  const all = read<string[]>(DISMISSED, []);
  if (!all.includes(jobId)) write(DISMISSED, [...all, jobId].slice(-200));
}

export function isDismissed(jobId: string): boolean {
  return read<string[]>(DISMISSED, []).includes(jobId);
}
