// Mailed links are hash routes (`…/#/reset-password?token=…`): the fragment
// keeps the token out of proxy logs and `Referer`. This app uses BrowserRouter,
// so the fragment is read once before the router mounts, held in a module
// variable (never location, query, history or storage) and the address bar
// is rewritten to the plain path.

interface MailLink {
  path: string;
  token: string;
}

let captured: MailLink | null = null;

/** Mailed fragment route → the route this app actually serves. */
const ROUTES: Record<string, string> = {
  "/reset-password": "/reset",
  "/account-recovery": "/account-recovery",
};

/** Call once, synchronously, before rendering. Idempotent. */
export function captureMailLink(): void {
  const hash = window.location.hash;
  if (!hash.startsWith("#/")) return;

  const [rawPath = "", rawQuery = ""] = hash.slice(1).split("?", 2);
  const target = ROUTES[rawPath];
  if (!target) return;

  const token = new URLSearchParams(rawQuery).get("token") ?? "";
  captured = token ? { path: target, token } : null;

  // Rewrite even for a malformed link: the person still asked for the screen.
  window.history.replaceState(null, "", target);
}

/** Reading does NOT consume (StrictMode double-renders); `clearMailToken` when spent. */
export function mailToken(path: string): string | null {
  return captured && captured.path === path ? captured.token : null;
}

/** Drop the token once the server has consumed it, or the page is done. */
export function clearMailToken(): void {
  captured = null;
}

/** Where the mailed link wanted to go, if this load came from one. */
export function mailLinkPath(): string | null {
  return captured?.path ?? null;
}
