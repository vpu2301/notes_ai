// Handing the sign-in to the browser's password manager, so it is typed
// once and autofilled after that.
//
// Safari and Firefox learn a password by watching the form itself, which
// is why the login inputs carry real `name` and `autocomplete`
// attributes. Chromium does that too, but its heuristic ("the password
// field vanished, so that was probably a login") is easy for a SPA to
// defeat: we sign in with fetch and then route away. So on Chromium we
// also ask outright through the Credential Management API.
//
// Everything here is best-effort — the API needs a secure context
// (https, or localhost in dev) and the user may say no.

interface PasswordCredentialCtor {
  new (data: { id: string; password: string; name?: string }): Credential;
}

function passwordCredential(): PasswordCredentialCtor | null {
  const ctor = (window as { PasswordCredential?: PasswordCredentialCtor }).PasswordCredential;
  return typeof ctor === "function" && navigator.credentials ? ctor : null;
}

/** Offer a just-used sign-in to the password manager. Never throws. */
export async function offerToSavePassword(email: string, password: string): Promise<void> {
  const PasswordCredential = passwordCredential();
  if (!PasswordCredential || !email || !password) return;
  try {
    await navigator.credentials.store(new PasswordCredential({ id: email, password, name: email }));
  } catch {
    /* declined, or no secure context — the form heuristic is the fallback */
  }
}

/**
 * After a deliberate sign-out, stop the manager from handing the
 * credential back without asking — otherwise "sign out" can look like it
 * did nothing on the next visit.
 */
export async function preventSilentSignIn(): Promise<void> {
  try {
    await navigator.credentials?.preventSilentAccess();
  } catch {
    /* no Credential Management API here */
  }
}
