/**
 * Browser-storage keys, all under one prefix.
 *
 * Three were written under the product's earlier name; `migrateStorageKeys`
 * carries their values over once so a remembered first-run flag or a
 * referral code is not lost by the rename.
 */
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
