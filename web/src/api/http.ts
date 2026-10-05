// Typed fetch wrapper: in-memory bearer token, single-flight refresh + one
// retry on 401, RFC 9457 problems, and the single step-up choke point.

import type { LoginResponse } from "./types";

/** Dev builds fall back to the dev stack's ports; prod fails at startup instead of calling localhost. */
function base(name: string, value: string | undefined, devDefault: string): string {
  if (value) return value;
  if (import.meta.env.PROD) {
    throw new Error(`Notes AI is not configured: ${name} is missing from this build.`);
  }
  return devDefault;
}

export const BASES = {
  auth: base("VITE_AUTH_BASE", import.meta.env.VITE_AUTH_BASE, "http://localhost:8000"),
  asr: base("VITE_ASR_BASE", import.meta.env.VITE_ASR_BASE, "http://localhost:8001"),
  notification: base("VITE_NOTIFICATION_BASE", import.meta.env.VITE_NOTIFICATION_BASE, "http://localhost:8004"),
  note: base("VITE_NOTE_BASE", import.meta.env.VITE_NOTE_BASE, "http://localhost:8006"),
} as const;

export type ServiceBase = keyof typeof BASES;

/**
 * Custom headers each service's CORS `allow_headers` accepts. A header the
 * target does not list fails preflight as an opaque TypeError, so widen a row
 * only after that service's `allow_headers` (its main.py) has caught up.
 */
const CORS_CUSTOM_HEADERS: Record<ServiceBase, readonly string[]> = {
  auth: ["X-Client-Type", "X-Request-Id"],
  asr: [],
  note: [],
  notification: [],
};

function allowsHeader(base: ServiceBase, name: string): boolean {
  return CORS_CUSTOM_HEADERS[base].includes(name);
}

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
  /** The `X-Request-Id` this call was sent with — shown as "ref" in error toasts. */
  readonly requestId?: string;

  constructor(status: number, problem: Problem, requestId?: string) {
    super(problem.detail || problem.title || `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
    this.requestId = requestId;
  }

  /** Human-safe message — problem `detail`, never raw JSON. */
  get detail(): string {
    return this.message;
  }

  get code(): string | undefined {
    return typeof this.problem.code === "string" ? this.problem.code : undefined;
  }

  /** The problem `type` URI, e.g. `https://errors.notes-ai/missing-read-purpose`. */
  get type(): string | undefined {
    return typeof this.problem.type === "string" ? this.problem.type : undefined;
  }

  /** Version-conflict style failure (stale expected_version). */
  get isConflict(): boolean {
    return this.status === 409 || this.status === 412;
  }

  /** Role denial from the permission gate (`deny: roles=[…] cannot …`); `messageFor` rewords it. */
  get isRoleDenial(): boolean {
    return this.status === 403 && this.detail.startsWith("deny:");
  }

  /** A problem extension member, e.g. `attempts_left`, `reauth_window_seconds`. */
  extra<T = unknown>(key: string): T | undefined {
    return this.problem[key] as T | undefined;
  }

  /** Seconds the server asked us to wait (`Retry-After`, echoed into the problem). */
  get retryAfter(): number | undefined {
    const raw = this.problem.retry_after;
    return typeof raw === "number" && Number.isFinite(raw) ? raw : undefined;
  }
}

async function parseProblem(res: Response): Promise<Problem> {
  // `Retry-After` is folded into the problem.
  const retryAfter = Number(res.headers.get("Retry-After"));
  const withRetry = (p: Problem): Problem =>
    Number.isFinite(retryAfter) && retryAfter > 0 ? { retry_after: retryAfter, ...p } : p;
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object") {
      const p = body as Record<string, unknown>;
      // FastAPI validation errors arrive as {detail: [...]}.
      if (Array.isArray(p.detail)) {
        const first = p.detail[0] as { msg?: string } | undefined;
        return withRetry({ status: res.status, detail: first?.msg ?? "Validation failed" });
      }
      if (p.detail && typeof p.detail === "object") {
        // Older services raise the whole problem document as the detail.
        return withRetry({ status: res.status, ...p, ...(p.detail as Problem) });
      }
      return withRetry({ status: res.status, ...(p as Problem) });
    }
  } catch {
    /* non-JSON body */
  }
  return withRetry({ status: res.status, detail: res.statusText || `HTTP ${res.status}` });
}

// ── in-memory access token ────────────────────────────────────────────

let accessToken: string | null = null;
/** Set once the server has said the session is over; a new token clears it. While set, bearer
 *  calls fail locally instead of each costing a 401 plus another doomed refresh. */
let sessionGone = false;

export function setAccessToken(token: string | null): void {
  accessToken = token;
  if (token) sessionGone = false;
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

// ── correlation id ────────────────────────────────────────────────────

/** UUID v4; `crypto.randomUUID` needs a secure context, so dev over LAN http needs the fallback. */
function requestId(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  const b = new Uint8Array(16);
  if (c && typeof c.getRandomValues === "function") {
    c.getRandomValues(b);
  } else {
    for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
  }
  b[6] = (b[6]! & 0x0f) | 0x40; // version 4
  b[8] = (b[8]! & 0x3f) | 0x80; // variant 10x
  const hex = [...b].map((n) => n.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

// ── step-up ───────────────────────────────────────────────────────────

/** Opens the reauth dialog; owned here so no page can bypass the step-up. */
type ReauthHandler = () => Promise<void>;

let reauthHandler: ReauthHandler | null = null;

export function setReauthHandler(h: ReauthHandler | null): void {
  reauthHandler = h;
}

/** `docs/api/error-codes.md`: 403 from any step-up endpoint. */
const REAUTH_CODE = "reauth_required";

async function isReauthRequired(res: Response): Promise<boolean> {
  if (res.status !== 403 || !reauthHandler) return false;
  // Clone: the caller still needs the original body if the step-up is declined.
  try {
    const problem = (await res.clone().json()) as Problem;
    return problem?.code === REAUTH_CODE;
  } catch {
    return false;
  }
}

/**
 * Role-gate denial (`403 deny: …`, no machine code). Roles are re-read at
 * token mint, so a token that predates a grant is refused until refreshed.
 */
async function isRoleDenial(res: Response): Promise<boolean> {
  if (res.status !== 403) return false;
  try {
    const problem = (await res.clone().json()) as Problem;
    return typeof problem?.detail === "string" && problem.detail.startsWith("deny:");
  } catch {
    return false;
  }
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
      headers: corsSafeHeaders("auth", requestId()),
      credentials: "include",
    });
    if (!res.ok) {
      if (res.status === 401) sessionGone = true;
      return false;
    }
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
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
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

/** Absolute URL of a service path — for `<a href>` / `<img src>`, not for `api()`. */
export function buildUrl(base: ServiceBase, path: string, query?: RequestOptions["query"]): string {
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

/** Headers this base accepts at preflight. `X-Client-Type` decides where the refresh token travels. */
function corsSafeHeaders(base: ServiceBase, rid: string): Record<string, string> {
  const headers: Record<string, string> = {};
  if (allowsHeader(base, "X-Client-Type")) headers["X-Client-Type"] = "web";
  if (allowsHeader(base, "X-Request-Id")) headers["X-Request-Id"] = rid;
  return headers;
}

async function rawRequest(
  base: ServiceBase,
  path: string,
  opts: RequestOptions,
): Promise<{ res: Response; requestId?: string }> {
  const rid = requestId();
  let body: BodyInit | undefined;
  const staticHeaders: Record<string, string> = corsSafeHeaders(base, rid);
  if (opts.form) {
    body = opts.form;
  } else if (opts.json !== undefined) {
    staticHeaders["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }

  // Built per attempt: a retry must carry the NEW access token.
  const doFetch = () =>
    fetch(buildUrl(base, path, opts.query), {
      method: opts.method ?? "GET",
      headers: {
        ...staticHeaders,
        ...(opts.auth !== false && accessToken
          ? { Authorization: `Bearer ${accessToken}` }
          : {}),
      },
      body,
      credentials: opts.credentials ? "include" : "same-origin",
      signal: opts.signal,
    });

  if (opts.auth !== false && sessionGone) {
    sessionListener.onAuthLost?.();
    throw new ApiError(401, { status: 401, code: "session_expired", detail: "Your session ended." }, rid);
  }

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

  // One silent refresh + retry on a 403 role denial (token may predate the grant).
  if (opts.auth !== false && (await isRoleDenial(res))) {
    if (await refreshSession()) res = await doFetch();
  }

  // One step-up + retry on 403 reauth_required; a declined dialog falls through with the 403.
  if (await isReauthRequired(res)) {
    try {
      await reauthHandler!();
      res = await doFetch();
    } catch {
      /* declined or failed — fall through with the 403 */
    }
  }
  // Only reported when it actually travelled.
  return { res, requestId: staticHeaders["X-Request-Id"] };
}

export async function api<T>(base: ServiceBase, path: string, opts: RequestOptions = {}): Promise<T> {
  const { res, requestId: rid } = await rawRequest(base, path, opts);
  if (!res.ok) {
    throw new ApiError(res.status, await parseProblem(res), rid);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function apiBlob(
  base: ServiceBase,
  path: string,
  opts: RequestOptions = {},
): Promise<Blob> {
  const { res, requestId: rid } = await rawRequest(base, path, opts);
  if (!res.ok) {
    throw new ApiError(res.status, await parseProblem(res), rid);
  }
  return res.blob();
}
