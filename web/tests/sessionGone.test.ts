import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, setAccessToken, setSessionListener } from "../src/api/http";

afterEach(() => {
  vi.unstubAllGlobals();
  setSessionListener({});
  setAccessToken(null);
});

describe("a session the server has ended", () => {
  it("fails bearer calls locally after one failed refresh, until a new token arrives", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(new URL(url).pathname);
        return new Response("{}", { status: 401 });
      }),
    );
    const onAuthLost = vi.fn();
    setSessionListener({ onAuthLost });
    setAccessToken("stale");

    await expect(api("note", "/v1/glossary/hint")).rejects.toBeInstanceOf(ApiError);
    expect(calls).toEqual(["/v1/glossary/hint", "/auth/refresh"]);
    expect(onAuthLost).toHaveBeenCalledTimes(1);

    // Every later call: no request to the service, no refresh, the same outcome.
    await expect(api("note", "/v1/glossary/hint")).rejects.toMatchObject({ status: 401, code: "session_expired" });
    await expect(api("note", "/v1/notes")).rejects.toMatchObject({ status: 401 });
    expect(calls).toEqual(["/v1/glossary/hint", "/auth/refresh"]);

    // Anonymous calls are untouched.
    await expect(api("note", "/v1/shared/x", { auth: false })).rejects.toMatchObject({ status: 401 });
    expect(calls.at(-1)).toBe("/v1/shared/x");

    // Signing in again (a new token) lifts it.
    setAccessToken("fresh");
    await expect(api("note", "/v1/notes")).rejects.toMatchObject({ status: 401 });
    expect(calls.slice(-2)).toEqual(["/v1/notes", "/auth/refresh"]);
  });
});
