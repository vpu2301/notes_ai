// Per-browser capture bookkeeping: jobs this browser started (only those
// auto-convert), pre-typed titles, resolved job → note links. Kept per
// workspace (`notesai.{tenantId}.capture.…`): job ids mean nothing in another one.

import { migrateToWorkspace, workspaceKey } from "./storageKeys";

const TITLES = "capture.titles";
const MINE = "capture.mine";
const LINKS = "capture.links";
const DISMISSED = "capture.dismissed";

let tenant: string | null = null;

/** Set before the signed-in tree renders (`WorkspaceScope`); the first call also moves pre-workspace keys. */
export function scopeCaptures(tenantId: string): void {
  if (tenant === tenantId) return;
  tenant = tenantId;
  migrateToWorkspace(tenantId, [TITLES, MINE, LINKS, DISMISSED]);
}

function storageKey(name: string): string {
  return tenant ? workspaceKey(tenant, name) : `notesai.${name}`;
}

function read<T>(name: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(storageKey(name));
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(name: string, value: unknown): void {
  try {
    localStorage.setItem(storageKey(name), JSON.stringify(value));
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
