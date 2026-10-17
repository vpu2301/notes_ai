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
import { activateWorkspace, forgetMyInvitations, listTenants } from "../api/account";
import type { ProfilePatch } from "../api/auth";
import {
  refreshSession,
  setAccessToken,
  setReauthHandler,
  setSessionListener,
  setWorkspaceMoved,
} from "../api/http";
import { preventSilentSignIn } from "../lib/credentials";
import type {
  AuthResult,
  Identity,
  LoginResponse,
  Membership,
  MeResponse,
  WorkspaceToken,
} from "../api/types";

export type AuthStatus = "restoring" | "authenticated" | "anonymous";

/** Tabs share one session; the tab that switches tells the others here. */
const WORKSPACE_CHANNEL = "notesai.workspace";

/** What a sign-in call hands back to the page that made it. */
export type SignInOutcome =
  | {
      kind: "authenticated";
      isNewIdentity: boolean;
      recoveryCodesLeft: number | null;
      /** Invitations the sign-up accepted; the session already landed in the first. */
      joinedTenantIds: string[];
    }
  | { kind: "mfa_required"; challengeId: string; methods: string[]; expiresIn: number };

interface AuthContextValue {
  status: AuthStatus;
  me: MeResponse | null;
  /** The global principal. */
  identity: Identity | null;
  /** Every workspace this identity belongs to. */
  memberships: Membership[];
  /** The workspace the current access token is scoped to. */
  activeTenantId: string | null;
  /** This account's role in the active workspace, or null when unknown. */
  activeRole: string | null;
  /** False for a Keycloak-issued session: auth-service cannot re-scope it (409 legacy_session). */
  canSwitchWorkspaces: boolean;
  /** Move this session to another workspace. Throws `ApiError`. */
  switchWorkspace: (tenantId: string) => Promise<void>;
  /** Adopt a token the server minted while it already moved the session (accept, leave). `joinedName` raises the banner. */
  enterWorkspace: (token: WorkspaceToken, joinedName?: string) => Promise<void>;
  /** "You joined <name>": set by an accepted invitation, cleared by its banner. */
  joinedWorkspace: string | null;
  dismissJoined: () => void;
  /** The session moved to this workspace in another tab; requests stay refused until `followWorkspace`. */
  workspaceMoved: { to: string } | null;
  /** Adopt the workspace the session moved to (the strip's one button). */
  followWorkspace: () => Promise<void>;
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

/** `useAuth` for a screen that only *prefers* to know who is signed in (null outside the provider). */
export function useAuthOptional(): AuthContextValue | null {
  return useContext(AuthContext);
}

/** `identity` wins; in keycloak mode it is null and the per-tenant `users` row is the fallback. */
function identityFromMe(me: MeResponse): Identity | null {
  if (me.identity) return me.identity;
  const u = me.db_user;
  if (!u) return null;
  return {
    id: u.sub,
    email: u.email,
    display_name: u.display_name ?? "",
    mfa_enabled: u.mfa_enrolled_at !== null,
    has_password: true, // `users` rows are Keycloak-era accounts
    status: u.status,
  };
}

/** Routes served to people with no account: never touch the session. */
export function isAnonymousRoute(pathname: string): boolean {
  return pathname.startsWith("/s/") || pathname === "/join" || pathname.startsWith("/join/");
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("restoring");
  const [me, setMe] = useState<MeResponse | null>(null);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [activeTenantId, setActiveTenantState] = useState<string | null>(null);
  const [workspaceMoved, setMovedState] = useState<{ to: string } | null>(null);
  const [joinedWorkspace, setJoinedWorkspace] = useState<string | null>(null);
  // Read by the refresh listener and the channel, which outlive a render.
  const activeTenantRef = useRef<string | null>(null);
  const setActiveTenantId = useCallback((tenantId: string | null) => {
    activeTenantRef.current = tenantId;
    setActiveTenantState(tenantId);
  }, []);
  const movedRef = useRef<string | null>(null);
  const [reauthPending, setReauthPending] = useState(false);
  const refreshTimer = useRef<number | null>(null);
  // In a ref, not state: a re-render must not lose the pending request.
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

  /** Where `http.ts` and the strip read "the session moved"; null clears both. */
  const markMoved = useCallback((tenantId: string | null) => {
    movedRef.current = tenantId;
    setWorkspaceMoved(tenantId);
    setMovedState(tenantId ? { to: tenantId } : null);
  }, []);

  /** The session is in `tenantId`; a mismatch with this tab's workspace blocks requests, never re-scopes silently. */
  const confirmWorkspace = useCallback(
    (tenantId: string | undefined) => {
      const active = activeTenantRef.current;
      if (!tenantId || !active) return;
      markMoved(tenantId === active ? null : tenantId);
    },
    [markMoved],
  );

  const becomeAnonymous = useCallback(() => {
    clearTimer();
    forgetMyInvitations();
    markMoved(null);
    setAccessToken(null);
    setMe(null);
    setIdentity(null);
    setMemberships([]);
    setActiveTenantId(null);
    setJoinedWorkspace(null);
    setStatus("anonymous");
  }, [clearTimer, markMoved]);

  /** Everything a fresh `AuthResult` tells us, applied in one place. */
  const adopt = useCallback(
    async (result: AuthResult): Promise<SignInOutcome> => {
      if (result.status === "mfa_required") {
        // First factor only: do not touch session state.
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
      const joined = result.joined_tenant_ids ?? [];
      const landed = (result.memberships ?? []).find((m) => m.tenant_id === joined[0]);
      if (landed) setJoinedWorkspace(landed.name);
      setStatus("authenticated");
      // Best-effort: a failed `/auth/me` must not undo a real sign-in.
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
        joinedTenantIds: joined,
      };
    },
    [scheduleRefresh],
  );

  useEffect(() => {
    setSessionListener({
      onRefreshed: (login: LoginResponse) => {
        scheduleRefresh(login.expires_in);
        confirmWorkspace(login.tenant_id);
      },
      onAuthLost: becomeAnonymous,
    });
    return () => setSessionListener({});
  }, [scheduleRefresh, becomeAnonymous, confirmWorkspace]);

  // Another tab switched: stop now rather than at this tab's next refresh.
  const channel = useRef<BroadcastChannel | null>(null);
  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;
    const ch = new BroadcastChannel(WORKSPACE_CHANNEL);
    ch.onmessage = (e: MessageEvent<{ tenant_id?: string }>) => confirmWorkspace(e.data?.tenant_id);
    channel.current = ch;
    return () => {
      ch.close();
      channel.current = null;
    };
  }, [confirmWorkspace]);

  // Restore the session on first load via the HttpOnly refresh cookie.
  useEffect(() => {
    let cancelled = false;
    if (isAnonymousRoute(window.location.pathname)) {
      // Never fire `/auth/refresh` here: the cookie rotates, and a stray
      // re-use revokes every session the person has elsewhere.
      setStatus("anonymous");
      return;
    }
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

  /** One `PATCH /auth/me`; omitted keys are left alone by the server. */
  const saveProfile = useCallback(async (patch: ProfilePatch) => {
    const updated = await authApi.patchMe(patch);
    setIdentity(updated);
  }, []);

  const setDisplayName = useCallback(
    async (name: string) => saveProfile({ display_name: name }),
    [saveProfile],
  );

  /** Re-read the identity after a server-side change (MFA, email) without a reload. */
  const refreshIdentity = useCallback(async () => {
    const meResp = await authApi.fetchMe();
    setMe(meResp);
    setIdentity(identityFromMe(meResp));
    setMemberships(meResp.memberships ?? []);
  }, []);

  /** `activeTenantId` changing remounts the signed-in tree (`WorkspaceScope`), so no stale rows stay on screen. */
  const enterWorkspace = useCallback(
    async (token: WorkspaceToken, joinedName?: string) => {
      setAccessToken(token.access_token);
      scheduleRefresh(token.expires_in);
      markMoved(null);
      setActiveTenantId(token.tenant_id);
      channel.current?.postMessage({ tenant_id: token.tenant_id });
      try {
        const meResp = await authApi.fetchMe();
        setMe(meResp);
        setIdentity(identityFromMe(meResp) ?? identity);
        setMemberships(meResp.memberships ?? []);
      } catch {
        /* the token is real; the profile read is a bonus */
      }
      if (joinedName) setJoinedWorkspace(joinedName);
    },
    [identity, scheduleRefresh, markMoved],
  );

  const switchWorkspace = useCallback(
    async (tenantId: string) => {
      if (tenantId === activeTenantId) return;
      await enterWorkspace(await activateWorkspace(tenantId));
    },
    [activeTenantId, enterWorkspace],
  );

  const dismissJoined = useCallback(() => setJoinedWorkspace(null), []);

  /** A switch the session already made: a refresh mints this tab a token there, then the tree remounts. */
  const followWorkspace = useCallback(async () => {
    const to = movedRef.current;
    if (!to) return;
    activeTenantRef.current = to;
    markMoved(null);
    // The refresh confirms the workspace again; a further move re-blocks.
    if (!(await refreshSession()) || movedRef.current) {
      activeTenantRef.current = activeTenantId;
      if (!movedRef.current) markMoved(to);
      return;
    }
    setActiveTenantId(to);
    try {
      const meResp = await authApi.fetchMe();
      setMe(meResp);
      setIdentity(identityFromMe(meResp) ?? identity);
      setMemberships(meResp.memberships ?? []);
    } catch {
      /* the token is real; the profile read is a bonus */
    }
  }, [activeTenantId, identity, markMoved]);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      /* revocation is best-effort from the client's side */
    }
    // Signing out must make the next visit ask before using a saved password.
    void preventSilentSignIn();
    becomeAnonymous();
  }, [becomeAnonymous]);

  // ── step-up: `http.ts` awaits `reauth()`; the dialog settles the same promise.

  const reauth = useCallback((): Promise<void> => {
    if (reauthWaiter.current) {
      // Second 403 while open: chain onto the one proof, no second dialog.
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

  // Falls back to the `users` row: `/auth/me` may not return memberships. `db_user` stays behind this file.
  const activeRole = useMemo(() => {
    const membership = memberships.find((m) => m.tenant_id === activeTenantId);
    return membership?.role ?? me?.db_user?.role ?? null;
  }, [memberships, activeTenantId, me]);

  // Keycloak issuers look like `…/realms/<name>`; the native issuer is the auth-service origin.
  const canSwitchWorkspaces = useMemo(() => {
    const iss = me?.claims.iss ?? "";
    return !iss.includes("/realms/");
  }, [me]);

  // Memberships carry the tenant's unique internal name (`tenant-a`); `GET /tenants` has the name people gave it.
  const [titles, setTitles] = useState<Record<string, string>>({});
  const membershipKey = memberships.map((m) => m.tenant_id).join(",");
  useEffect(() => {
    if (status !== "authenticated" || !canSwitchWorkspaces || !membershipKey) return;
    let live = true;
    listTenants()
      .then((r) => live && setTitles(Object.fromEntries(r.items.map((t) => [t.id, t.display_name || t.name]))))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [status, canSwitchWorkspaces, membershipKey]);
  const namedMemberships = useMemo(
    () => memberships.map((m) => ({ ...m, name: titles[m.tenant_id] || m.name })),
    [memberships, titles],
  );

  const value = useMemo(
    () => ({
      status,
      me,
      identity,
      memberships: namedMemberships,
      activeTenantId,
      activeRole,
      canSwitchWorkspaces,
      switchWorkspace,
      enterWorkspace,
      joinedWorkspace,
      dismissJoined,
      workspaceMoved,
      followWorkspace,
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
      namedMemberships,
      activeTenantId,
      activeRole,
      canSwitchWorkspaces,
      switchWorkspace,
      enterWorkspace,
      joinedWorkspace,
      dismissJoined,
      workspaceMoved,
      followWorkspace,
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
