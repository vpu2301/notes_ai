// The bridge between the links auth-service mails and this app's routes.
//
// `domain/compose.py` builds them as hash routes —
// `…/#/reset-password?token=…` and `…/#/account-recovery?token=…` — and the
// comment there explains why the token rides in the fragment: a fragment is
// never sent to a server, so the token stays out of every proxy access log
// between here and the user, and out of `Referer` when the page loads a
// font. That is worth keeping.
//
// This app runs `BrowserRouter`, though, so those URLs land on `/` with a
// hash React Router ignores, `RequireAuth` bounces them to `/login`, and the
// token is dropped. (The hash form was written for the sibling Notes AI SPA;
// the reset link has never worked against this one.)
//
// So: read the fragment once, before the router mounts, keep the token in a
// module variable, and rewrite the address bar to the plain path. The token
// is never in `location`, never in a query string, never in `history`, and
// never in storage — it lives for one page load, which is all a single-use
// link needs.

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

/**
 * Call once, synchronously, before rendering. Safe to call again: after the
 * first call there is no hash left to read.
 */
export function captureMailLink(): void {
  const hash = window.location.hash;
  if (!hash.startsWith("#/")) return;

  const [rawPath = "", rawQuery = ""] = hash.slice(1).split("?", 2);
  const target = ROUTES[rawPath];
  if (!target) return;

  const token = new URLSearchParams(rawQuery).get("token") ?? "";
  captured = token ? { path: target, token } : null;

  // Rewrite even when the token was missing or the link was malformed: the
  // person still asked for the reset screen, and leaving them on `/` with a
  // dead fragment is the worse answer.
  window.history.replaceState(null, "", target);
}

/**
 * The token for a screen. Reading does NOT consume it: React re-renders
 * (twice in StrictMode) and a read-once accessor would hand the second
 * render a null. `clearMailToken` is called when the token has actually
 * been spent.
 */
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
