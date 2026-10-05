// Password-manager hand-off. Safari/Firefox learn from the form (hence real
// `name`/`autocomplete` on the inputs); Chromium's heuristic misses a fetch +
// route-away SPA login, so the Credential Management API is asked outright.
// Best-effort: needs a secure context and the user may say no.

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

/** After sign-out, stop the manager from silently handing the credential back. */
export async function preventSilentSignIn(): Promise<void> {
  try {
    await navigator.credentials?.preventSilentAccess();
  } catch {
    /* no Credential Management API here */
  }
}
