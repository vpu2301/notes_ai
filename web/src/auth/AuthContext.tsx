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
import { refreshSession, setAccessToken, setSessionListener } from "../api/http";
import type { LoginResponse, MeResponse } from "../api/types";

export type AuthStatus = "restoring" | "authenticated" | "anonymous";

interface AuthContextValue {
  status: AuthStatus;
  me: MeResponse | null;
  displayName: string;
  login: (email: string, password: string, otp?: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("restoring");
  const [me, setMe] = useState<MeResponse | null>(null);
  const refreshTimer = useRef<number | null>(null);

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
    setStatus("anonymous");
  }, [clearTimer]);

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
      setStatus("authenticated");
    },
    [scheduleRefresh],
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      /* revocation is best-effort from the client's side */
    }
    becomeAnonymous();
  }, [becomeAnonymous]);

  const displayName = useMemo(() => {
    const user = me?.db_user;
    return user?.display_name || user?.email || "Account";
  }, [me]);

  const value = useMemo(
    () => ({ status, me, displayName, login, logout }),
    [status, me, displayName, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
