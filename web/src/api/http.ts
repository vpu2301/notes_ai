// Typed fetch wrapper: bearer auth from an in-memory token,
// single-flight silent refresh + one retry on 401, RFC-9457 problem parsing.

import type { LoginResponse } from "./types";

export const BASES = {
  auth: import.meta.env.VITE_AUTH_BASE ?? "http://localhost:8000",
  asr: import.meta.env.VITE_ASR_BASE ?? "http://localhost:8001",
  notification: import.meta.env.VITE_NOTIFICATION_BASE ?? "http://localhost:8004",
  note: import.meta.env.VITE_NOTE_BASE ?? "http://localhost:8006",
} as const;

export type ServiceBase = keyof typeof BASES;

// ── RFC 9457 problems ─────────────────────────────────────────────────

export interface Problem {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  /** machine code some services attach (e.g. otp_required) */
  code?: string;
  error_kind?: string;
  [key: string]: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem;

  constructor(status: number, problem: Problem) {
    super(problem.detail || problem.title || `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }

  /** Human-safe message — problem `detail`, never raw JSON. */
  get detail(): string {
    return this.message;
  }

  get code(): string | undefined {
    return typeof this.problem.code === "string" ? this.problem.code : undefined;
  }

  /** Version-conflict style failure (stale expected_version). */
  get isConflict(): boolean {
    return this.status === 409 || this.status === 412;
  }
}

async function parseProblem(res: Response): Promise<Problem> {
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object") {
      const p = body as Record<string, unknown>;
      // FastAPI sometimes wraps plain HTTPException as {detail: "..."} and
      // validation errors as {detail: [...]}.
      if (Array.isArray(p.detail)) {
        const first = p.detail[0] as { msg?: string } | undefined;
        return { status: res.status, detail: first?.msg ?? "Validation failed" };
      }
      return { status: res.status, ...(p as Problem) };
    }
  } catch {
    /* non-JSON body */
  }
  return { status: res.status, detail: res.statusText || `HTTP ${res.status}` };
}

// ── in-memory access token ────────────────────────────────────────────

let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

type SessionListener = {
  onRefreshed?: (login: LoginResponse) => void;
  onAuthLost?: () => void;
};

let sessionListener: SessionListener = {};

export function setSessionListener(l: SessionListener): void {
  sessionListener = l;
}

// ── single-flight silent refresh ──────────────────────────────────────

let refreshInFlight: Promise<boolean> | null = null;

export function refreshSession(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = doRefresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

async function doRefresh(): Promise<boolean> {
  try {
    const res = await fetch(`${BASES.auth}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
    if (!res.ok) return false;
    const login = (await res.json()) as LoginResponse;
    setAccessToken(login.access_token);
    sessionListener.onRefreshed?.(login);
    return true;
  } catch {
    return false;
  }
}

// ── the request helper ────────────────────────────────────────────────

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  /** JSON body */
  json?: unknown;
  /** multipart body (wins over json) */
  form?: FormData;
  /** query params; arrays are repeated, null/undefined skipped */
  query?: Record<string, string | number | boolean | string[] | null | undefined>;
  /** attach Authorization: Bearer (default true) */
  auth?: boolean;
  /** send cookies (auth-service endpoints) */
  credentials?: boolean;
  signal?: AbortSignal;
}

function buildUrl(base: ServiceBase, path: string, query?: RequestOptions["query"]): string {
  const url = new URL(BASES[base] + path);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === null || value === undefined) continue;
      if (Array.isArray(value)) {
        for (const v of value) url.searchParams.append(key, v);
      } else {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

async function rawRequest(
  base: ServiceBase,
  path: string,
  opts: RequestOptions,
): Promise<Response> {
  const headers: Record<string, string> = {};
  if (opts.auth !== false && accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  }
  let body: BodyInit | undefined;
  if (opts.form) {
    body = opts.form;
  } else if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }

  const doFetch = () =>
    fetch(buildUrl(base, path, opts.query), {
      method: opts.method ?? "GET",
      headers: {
        ...headers,
        ...(opts.auth !== false && accessToken
          ? { Authorization: `Bearer ${accessToken}` }
          : {}),
      },
      body,
      credentials: opts.credentials ? "include" : "same-origin",
      signal: opts.signal,
    });

  let res = await doFetch();

  // One silent refresh + retry on 401 for bearer-authenticated calls.
  if (res.status === 401 && opts.auth !== false) {
    const refreshed = await refreshSession();
    if (refreshed) {
      res = await doFetch();
    } else {
      sessionListener.onAuthLost?.();
    }
  }
  return res;
}

export async function api<T>(base: ServiceBase, path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await rawRequest(base, path, opts);
  if (!res.ok) {
    throw new ApiError(res.status, await parseProblem(res));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function apiBlob(
  base: ServiceBase,
  path: string,
  opts: RequestOptions = {},
): Promise<Blob> {
  const res = await rawRequest(base, path, opts);
  if (!res.ok) {
    throw new ApiError(res.status, await parseProblem(res));
  }
  return res.blob();
}

/** Best human message for any thrown value. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof TypeError) return "Cannot reach the server — is it running?";
  if (err instanceof Error) return err.message;
  return "Something went wrong";
}
