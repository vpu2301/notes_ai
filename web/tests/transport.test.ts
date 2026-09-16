import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  api,
  setAccessToken,
  setReauthHandler,
  setSessionListener,
} from "../src/api/http";

/**
 * §F and §I of IDX-W1, as assertions:
 *   - every auth call declares `X-Client-Type: web` and carries a request id;
 *   - the refresh cookie is the only refresh channel a browser has;
 *   - a 403 `reauth_required` goes through the one dialog and retries once,
 *     and a cancelled dialog does not retry.
 */

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;

let calls: { url: string; init: RequestInit }[] = [];

function mockFetch(handler: Handler) {
  const fn = vi.fn(async (url: unknown, init: unknown = {}) => {
    const record = { url: String(url), init: (init ?? {}) as RequestInit };
    calls.push(record);
    return handler(record.url, record.init);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const header = (init: RequestInit, name: string) =>
  (init.headers as Record<string, string> | undefined)?.[name];

beforeEach(() => {
  calls = [];
  setAccessToken(null);
  setReauthHandler(null);
  setSessionListener({});
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("transport headers", () => {
  it("declares the client type on auth-service calls", async () => {
    mockFetch(() => json({ ok: true }));
    await api("auth", "/auth/me");
    expect(header(calls[0]!.init, "X-Client-Type")).toBe("web");
  });

  it("does not declare a client type to the other services", async () => {
    mockFetch(() => json({ ok: true }));
    await api("note", "/v1/notes");
    expect(header(calls[0]!.init, "X-Client-Type")).toBeUndefined();
  });

  // Each of these bases is a different origin from the SPA, so a request
  // header the service does not list in `allow_headers` fails the browser
  // preflight and the real call is never sent — it surfaces as a bare
  // network error, not as a 4xx. note-service, asr-service and
  // notification-service still allow only `Authorization` and
  // `Content-Type`; sending `X-Request-Id` to them took every note, ASR and
  // notification call offline while auth-service kept working.
  const SAFELISTED = ["accept", "accept-language", "content-language", "content-type"];
  const CORS_ALLOWED: Record<string, string[]> = {
    auth: [...SAFELISTED, "authorization", "x-client-type", "x-request-id"],
    note: [...SAFELISTED, "authorization"],
    asr: [...SAFELISTED, "authorization"],
    notification: [...SAFELISTED, "authorization"],
  };

  it.each(Object.keys(CORS_ALLOWED))("sends only preflight-legal headers to %s", async (base) => {
    mockFetch(() => json({ ok: true }));
    setAccessToken("token");
    await api(base as Parameters<typeof api>[0], "/anything", {
      method: "POST",
      json: { a: 1 },
    });
    const sent = Object.keys((calls[0]!.init.headers ?? {}) as Record<string, string>).map((h) =>
      h.toLowerCase(),
    );
    expect(sent.filter((h) => !CORS_ALLOWED[base]!.includes(h))).toEqual([]);
  });

  it("omits the request id where it would break the preflight", async () => {
    mockFetch(() => json({ detail: "nope" }, 500));
    const err = await api("note", "/v1/notes").catch((e: unknown) => e);
    expect(header(calls[0]!.init, "X-Request-Id")).toBeUndefined();
    // No ref is reported rather than one the server never saw.
    expect((err as ApiError).requestId).toBeUndefined();
  });

  it("sends a v4 request id on every call and reports it on failure", async () => {
    mockFetch(() => json({ detail: "nope" }, 500));
    const err = await api("auth", "/auth/me").catch((e: unknown) => e);
    const sent = header(calls[0]!.init, "X-Request-Id");
    expect(sent).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect((err as ApiError).requestId).toBe(sent);
  });

  it("only sends cookies where it was asked to", async () => {
    mockFetch(() => json({}));
    await api("auth", "/auth/email/start", { method: "POST", credentials: true, auth: false });
    await api("note", "/v1/notes");
    expect(calls[0]!.init.credentials).toBe("include");
    expect(calls[1]!.init.credentials).toBe("same-origin");
  });
});

describe("the refresh cookie is the only refresh channel", () => {
  it("never persists a refresh_token that leaks into a web response", async () => {
    // The server sends this field to native clients only. If one ever
    // appeared in a web response it must go nowhere — so watch every write
    // path a browser has.
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    mockFetch(() =>
      json({
        status: "authenticated",
        access_token: "at",
        expires_in: 900,
        refresh_token: "SECRET-DO-NOT-KEEP",
        refresh_expires_in: 2592000,
      }),
    );
    const result = await api<Record<string, unknown>>("auth", "/auth/email/verify", {
      method: "POST",
      credentials: true,
      auth: false,
    });

    expect(setItem).not.toHaveBeenCalled();
    expect(document.cookie).not.toContain("SECRET-DO-NOT-KEEP");
    expect(String(result.access_token)).toBe("at");
    setItem.mockRestore();
  });

  it("has no code anywhere that reads refresh_token", async () => {
    // The strongest form of §M's "web responses are never inspected for a
    // refresh token": not an assertion about one call, but the absence of
    // any reader in the whole client. `AuthResult` deliberately does not
    // declare the field, so this fails if somebody adds it back.
    const { readFileSync, readdirSync, statSync } = await import("node:fs");
    const { join, resolve } = await import("node:path");

    const walk = (dir: string): string[] =>
      readdirSync(dir).flatMap((entry: string) => {
        const full = join(dir, entry);
        return statSync(full).isDirectory() ? walk(full) : /\.tsx?$/.test(entry) ? [full] : [];
      });

    const offenders = walk(resolve(__dirname, "../src")).filter((file) => {
      // Comments are stripped: the field is discussed at length, and should be.
      const code = readFileSync(file, "utf8")
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/\/\/.*$/gm, "");
      // As an identifier, not as a substring: `no_refresh_token` is an
      // error code the UI is supposed to handle, not a token being read.
      return /(?<![A-Za-z0-9_])refresh_token(?![A-Za-z0-9_])/.test(code);
    });

    expect(offenders).toEqual([]);
  });

  it("refreshes with the cookie and no body", async () => {
    mockFetch((url) =>
      url.endsWith("/auth/refresh")
        ? json({ access_token: "new", expires_in: 900 })
        : json({ detail: "unauthorized" }, 401),
    );
    setAccessToken("stale");
    await api("note", "/v1/notes").catch(() => undefined);

    const refresh = calls.find((c) => c.url.endsWith("/auth/refresh"));
    expect(refresh).toBeDefined();
    expect(refresh!.init.credentials).toBe("include");
    expect(refresh!.init.body).toBeUndefined();
  });
});

describe("step-up", () => {
  const stepUp = () => json({ code: "reauth_required", detail: "confirm it is you" }, 403);

  it("opens the dialog once and retries the original request", async () => {
    let attempt = 0;
    mockFetch(() => (++attempt === 1 ? stepUp() : json({ done: true })));
    const handler = vi.fn(async () => undefined);
    setReauthHandler(handler);

    await expect(api("auth", "/auth/sessions/revoke-others", { method: "POST" })).resolves.toEqual({
      done: true,
    });
    expect(handler).toHaveBeenCalledTimes(1);
    expect(attempt).toBe(2);
  });

  it("retries exactly once — a second 403 is a refusal, not a loop", async () => {
    let attempt = 0;
    mockFetch(() => {
      attempt++;
      return stepUp();
    });
    setReauthHandler(async () => undefined);

    const err = await api("auth", "/auth/account/delete", { method: "POST" }).catch(
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(403);
    expect(attempt).toBe(2);
  });

  it("does not retry when the dialog is cancelled", async () => {
    let attempt = 0;
    mockFetch(() => {
      attempt++;
      return stepUp();
    });
    setReauthHandler(async () => {
      throw new Error("reauth cancelled");
    });

    const err = await api("auth", "/auth/account/delete", { method: "POST" }).catch(
      (e: unknown) => e,
    );
    expect((err as ApiError).status).toBe(403);
    expect((err as ApiError).code).toBe("reauth_required");
    expect(attempt).toBe(1);
  });

  it("leaves an unrelated 403 alone", async () => {
    mockFetch(() => json({ code: "not_a_member", detail: "no" }, 403));
    const handler = vi.fn(async () => undefined);
    setReauthHandler(handler);

    await api("auth", "/auth/me").catch(() => undefined);
    expect(handler).not.toHaveBeenCalled();
  });

  it("carries a token refreshed mid-flight into the retry", async () => {
    // The retry must not re-send the token that was rejected.
    mockFetch((url) => {
      if (url.endsWith("/auth/refresh")) return json({ access_token: "fresh", expires_in: 900 });
      const auth = header(calls[calls.length - 1]!.init, "Authorization");
      return auth === "Bearer fresh" ? json({ ok: true }) : json({ detail: "no" }, 401);
    });
    setAccessToken("stale");

    await expect(api("note", "/v1/notes")).resolves.toEqual({ ok: true });
  });
});
