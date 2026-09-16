import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import * as authApi from "../api/auth";
import type { ProfilePatch } from "../api/auth";
import {
  refreshSession,
  setAccessToken,
  setReauthHandler,
  setSessionListener,
} from "../api/http";
import { preventSilentSignIn } from "../lib/credentials";
import type { AuthResult, Identity, LoginResponse, Membership, MeResponse } from "../api/types";

export type AuthStatus = "restoring" | "authenticated" | "anonymous";

/** What a sign-in call hands back to the page that made it. */
export type SignInOutcome =
  | { kind: "authenticated"; isNewIdentity: boolean; recoveryCodesLeft: number | null }
  | { kind: "mfa_required"; challengeId: string; methods: string[]; expiresIn: number };

interface AuthContextValue {
  status: AuthStatus;
  me: MeResponse | null;
  /** The global principal. Survives IDX-B2's removal of `db_user`. */
  identity: Identity | null;
  /** Every workspace this identity belongs to — W2's switcher reads this. */
  memberships: Membership[];
  /** The workspace the current access token is scoped to. */
  activeTenantId: string | null;
  /** This account's role in the active workspace, or null when unknown. */
  activeRole: string | null;
  displayName: string;
  /** Password sign-in. Throws `ApiError`; `otp_required` means try again with `otp`. */
  login: (email: string, password: string, otp?: string) => Promise<void>;
  /** Email one-time code. May return `mfa_required` rather than a session. */
  signInWithEmailCode: (challengeId: string, code: string) => Promise<SignInOutcome>;
  /** Finish an `mfa_required` sign-in. */
  completeMfa: (
    challengeId: string,
    method: "totp" | "recovery_code",
    code: string,
  ) => Promise<SignInOutcome>;
  /** Adopt an already-obtained session (the reset flow signs in afterwards). */
  adopt: (result: AuthResult) => Promise<SignInOutcome>;
  setDisplayName: (name: string) => Promise<void>;
  /** The whole profile patch — `/welcome` sends a name and a time zone at once. */
  saveProfile: (patch: ProfilePatch) => Promise<void>;
  /** Re-read the identity after something changed it (MFA, email). */
  refreshIdentity: () => Promise<void>;
  logout: () => Promise<void>;
  /** Opened by `http.ts` on a 403 `reauth_required`; resolves when the server accepts. */
  reauth: () => Promise<void>;
  /** Internal: the dialog host reads this. */
  reauthPending: boolean;
  resolveReauth: (ok: boolean) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/**
 * The person behind a `/auth/me`, whichever half of the cut-over answered.
 *
 * `routers/me.py` returns `identity` since IDX-B3, and it wins whenever it
 * is there. It is null in **keycloak mode**, where there are no
 * `identities` rows at all, so the per-tenant `users` row is still the
 * fallback — that is a live deployment shape, not legacy tolerance, and
 * this branch goes when IDX-B2 retires the table.
 */
function identityFromMe(me: MeResponse): Identity | null {
  if (me.identity) return me.identity;
  const u = me.db_user;
  if (!u) return null;
  return {
    id: u.sub,
    email: u.email,
    display_name: u.display_name ?? "",
    mfa_enabled: u.mfa_enrolled_at !== null,
    has_password: true, // a `users` row only exists in the Keycloak era
    status: u.status,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("restoring");
  const [me, setMe] = useState<MeResponse | null>(null);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [activeTenantId, setActiveTenantId] = useState<string | null>(null);
  const [reauthPending, setReauthPending] = useState(false);
  const refreshTimer = useRef<number | null>(null);
  // The promise `http.ts` is waiting on while the dialog is open.
  const reauthWaiter = useRef<{ resolve: () => void; reject: (e: Error) => void } | null>(null);

  const clearTimer = useCallback(() => {
    if (refreshTimer.current !== null) {
      window.clearTimeout(refreshTimer.current);
      refreshTimer.current = null;
    }
  }, []);

  /** Silent refresh a minute before the access token expires. */
  const scheduleRefresh = useCallback(
    (expiresInSeconds: number) => {
      clearTimer();
      const delayMs = Math.max(10, expiresInSeconds - 60) * 1000;
      refreshTimer.current = window.setTimeout(() => {
        void refreshSession();
      }, delayMs);
    },
    [clearTimer],
  );

  const becomeAnonymous = useCallback(() => {
    clearTimer();
    setAccessToken(null);
    setMe(null);
    setIdentity(null);
    setMemberships([]);
    setActiveTenantId(null);
    setStatus("anonymous");
  }, [clearTimer]);

  /** Everything a fresh `AuthResult` tells us, applied in one place. */
  const adopt = useCallback(
    async (result: AuthResult): Promise<SignInOutcome> => {
      if (result.status === "mfa_required") {
        // No token, no identity, nothing to hydrate — that is the whole
        // point of the challenge. Do NOT touch the session state here.
        return {
          kind: "mfa_required",
          challengeId: result.challenge_id ?? "",
          methods: result.methods ?? ["totp"],
          expiresIn: result.expires_in,
        };
      }
      setAccessToken(result.access_token);
      scheduleRefresh(result.expires_in);
      setIdentity(result.identity);
      setMemberships(result.memberships ?? []);
      setActiveTenantId(result.tenant_id || result.default_tenant_id || null);
      setStatus("authenticated");
      // Best-effort: the session is already real, and a `/auth/me` that
      // fails should not undo a successful sign-in.
      try {
        const meResp = await authApi.fetchMe();
        setMe(meResp);
        if (!result.identity) setIdentity(identityFromMe(meResp));
      } catch {
        /* claims came with the AuthResult; the extra call is a bonus */
      }
      return {
        kind: "authenticated",
        isNewIdentity: result.is_new_identity,
        recoveryCodesLeft: result.recovery_codes_left,
      };
    },
    [scheduleRefresh],
  );

  useEffect(() => {
    setSessionListener({
      onRefreshed: (login: LoginResponse) => scheduleRefresh(login.expires_in),
      onAuthLost: becomeAnonymous,
    });
    return () => setSessionListener({});
  }, [scheduleRefresh, becomeAnonymous]);

  // Restore the session on first load via the HttpOnly refresh cookie.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const ok = await refreshSession();
      if (cancelled) return;
      if (!ok) {
        setStatus("anonymous");
        return;
      }
      try {
        const meResp = await authApi.fetchMe();
        if (cancelled) return;
        setMe(meResp);
        setIdentity(identityFromMe(meResp));
        setMemberships(meResp.memberships ?? []);
        setActiveTenantId(meResp.claims.tid);
        setStatus("authenticated");
      } catch {
        if (!cancelled) becomeAnonymous();
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => clearTimer, [clearTimer]);

  const login = useCallback(
    async (email: string, password: string, otp?: string) => {
      const resp = await authApi.login(email, password, otp);
      setAccessToken(resp.access_token);
      scheduleRefresh(resp.expires_in);
      const meResp = await authApi.fetchMe();
      setMe(meResp);
      setIdentity(identityFromMe(meResp));
      setMemberships(meResp.memberships ?? []);
      setActiveTenantId(meResp.claims.tid);
      setStatus("authenticated");
    },
    [scheduleRefresh],
  );

  const signInWithEmailCode = useCallback(
    async (challengeId: string, code: string) => adopt(await authApi.emailVerify(challengeId, code)),
    [adopt],
  );

  const completeMfa = useCallback(
    async (challengeId: string, method: "totp" | "recovery_code", code: string) =>
      adopt(await authApi.mfaVerify(challengeId, method, code)),
    [adopt],
  );

  /**
   * One `PATCH /auth/me`, whatever combination of fields it carries.
   *
   * Omitted keys are left alone by the server, so a caller that only knows
   * the time zone does not have to re-send a name it never read — which
   * matters on `/welcome`, where "skip" still has a time zone worth saving.
   */
  const saveProfile = useCallback(async (patch: ProfilePatch) => {
    const updated = await authApi.patchMe(patch);
    setIdentity(updated);
  }, []);

  const setDisplayName = useCallback(
    async (name: string) => saveProfile({ display_name: name }),
    [saveProfile],
  );

  /**
   * Pull the identity again after a change the server made rather than we
   * did — enrolling a second factor, or moving the login address. Cheaper
   * and far less rude than reloading the page, which would throw away an
   * unsaved note to refresh a boolean.
   */
  const refreshIdentity = useCallback(async () => {
    const meResp = await authApi.fetchMe();
    setMe(meResp);
    setIdentity(identityFromMe(meResp));
    setMemberships(meResp.memberships ?? []);
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      /* revocation is best-effort from the client's side */
    }
    // A saved password stays saved, but signing out has to mean the next
    // visit asks before using it.
    void preventSilentSignIn();
    becomeAnonymous();
  }, [becomeAnonymous]);

  // ── step-up ──────────────────────────────────────────────────────────
  //
  // `http.ts` calls `reauth()` and awaits it; the dialog resolves or
  // rejects the same promise. Keeping the waiter in a ref (not state)
  // means a re-render cannot lose the pending request.

  const reauth = useCallback((): Promise<void> => {
    if (reauthWaiter.current) {
      // A second 403 while the dialog is already open: both callers wait
      // on the one proof rather than stacking two dialogs.
      return new Promise<void>((resolve, reject) => {
        const prev = reauthWaiter.current!;
        reauthWaiter.current = {
          resolve: () => {
            prev.resolve();
            resolve();
          },
          reject: (e) => {
            prev.reject(e);
            reject(e);
          },
        };
      });
    }
    return new Promise<void>((resolve, reject) => {
      reauthWaiter.current = { resolve, reject };
      setReauthPending(true);
    });
  }, []);

  const resolveReauth = useCallback((ok: boolean) => {
    const waiter = reauthWaiter.current;
    reauthWaiter.current = null;
    setReauthPending(false);
    if (!waiter) return;
    if (ok) waiter.resolve();
    else waiter.reject(new Error("reauth cancelled"));
  }, []);

  useEffect(() => {
    setReauthHandler(reauth);
    return () => setReauthHandler(null);
  }, [reauth]);

  const displayName = useMemo(
    () => identity?.display_name || identity?.email || "Account",
    [identity],
  );

  /**
   * The role in the active workspace.
   *
   * Prefers the membership list, and falls back to the `users` row's role —
   * because `/auth/me` does not return `memberships` yet, so on a plain page
   * load the list is empty and a workspace owner would look like a stranger
   * in their own workspace. The fallback goes here rather than in a screen so
   * that `db_user` stays behind this one file (IDX-B2 deletes it).
   */
  const activeRole = useMemo(() => {
    const membership = memberships.find((m) => m.tenant_id === activeTenantId);
    return membership?.role ?? me?.db_user?.role ?? null;
  }, [memberships, activeTenantId, me]);

  const value = useMemo(
    () => ({
      status,
      me,
      identity,
      memberships,
      activeTenantId,
      activeRole,
      displayName,
      login,
      signInWithEmailCode,
      completeMfa,
      adopt,
      setDisplayName,
      saveProfile,
      refreshIdentity,
      logout,
      reauth,
      reauthPending,
      resolveReauth,
    }),
    [
      status,
      me,
      identity,
      memberships,
      activeTenantId,
      activeRole,
      displayName,
      login,
      signInWithEmailCode,
      completeMfa,
      adopt,
      setDisplayName,
      saveProfile,
      refreshIdentity,
      logout,
      reauth,
      reauthPending,
      resolveReauth,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
