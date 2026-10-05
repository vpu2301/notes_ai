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
