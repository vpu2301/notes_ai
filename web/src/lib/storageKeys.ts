/** Browser-storage keys under one prefix; `migrateStorageKeys` carries over pre-rename values once. */
export const REF_KEY = "notesai.ref";
export const FIRST_RUN_KEY = "notesai.first_run_seen";

const RENAMED: [old: string, next: string][] = [
  ["klarnote.ref", REF_KEY],
  ["klarnote.first_run_seen", FIRST_RUN_KEY],
];

export function migrateStorageKeys(): void {
  for (const store of [localStorage, sessionStorage]) {
    for (const [old, next] of RENAMED) {
      try {
        const value = store.getItem(old);
        if (value === null) continue;
        if (store.getItem(next) === null) store.setItem(next, value);
        store.removeItem(old);
      } catch {
        /* storage unavailable */
      }
    }
  }
}

/** `notesai.{tenantId}.{name}`: bookkeeping that belongs to one workspace. */
export function workspaceKey(tenantId: string, name: string): string {
  return `notesai.${tenantId}.${name}`;
}

/** Unscoped `notesai.{name}` values predate workspaces, so they can only be the active one's: move them once. */
export function migrateToWorkspace(tenantId: string, names: readonly string[]): void {
  for (const name of names) {
    try {
      const old = `notesai.${name}`;
      const value = localStorage.getItem(old);
      if (value === null) continue;
      const next = workspaceKey(tenantId, name);
      if (localStorage.getItem(next) === null) localStorage.setItem(next, value);
      localStorage.removeItem(old);
    } catch {
      /* storage unavailable */
    }
  }
}
