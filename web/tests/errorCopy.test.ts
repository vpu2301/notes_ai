import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { ApiError } from "../src/api/http";
import { attemptsLeft, hasCopy, messageFor, messageWithRef } from "../src/lib/errorCopy";

/**
 * The acceptance criterion: "Every error code emitted by the A3–A5/B1
 * endpoints used here has a mapped, non-technical message (a test iterates
 * docs/api/error-codes.md)."
 *
 * So the catalogue is the fixture. Adding a code to the docs without adding
 * copy for it fails here, which is the point — the alternative is the
 * server's developer-facing `detail` leaking into the UI.
 */
const CATALOGUE = resolve(__dirname, "../../docs/api/error-codes.md");

/**
 * Codes the web client does not raise, each with the reason. This list is
 * the honest part of the test: it says what is NOT covered rather than
 * quietly passing. IDX-W2 removed `rotation_in_progress` and
 * `personal_workspace` from it — the devices screen surfaces both now.
 */
const OUT_OF_SCOPE = new Map<string, string>([
  ["invalid_client", "POST /auth/oauth/token — device and service grants (B1b), no web caller"],
  ["unsupported_grant_type", "as above"],
  ["client_rate_limited", "as above"],
  ["client_locked", "as above"],
  ["try_again", "as above"],
  ["model_not_configured", "note-service /ask, not an auth flow"],
  ["model_unavailable", "as above"],
]);

function codesFromCatalogue(): string[] {
  const md = readFileSync(CATALOGUE, "utf8");
  const codes = new Set<string>();
  for (const line of md.split("\n")) {
    // Table rows look like: | `code_name` | 400 | where | meaning |
    const m = /^\|\s*`([a-z0-9_]+)`/.exec(line.trim());
    if (m?.[1]) codes.add(m[1]);
  }
  return [...codes];
}

describe("error copy", () => {
  const codes = codesFromCatalogue();

  it("reads the catalogue", () => {
    // A silent zero here would make every assertion below vacuous.
    expect(codes.length).toBeGreaterThan(30);
  });

  it.each(codes.filter((c) => !OUT_OF_SCOPE.has(c)))("has a message for %s", (code) => {
    expect(hasCopy(code)).toBe(true);
  });

  it("documents why each uncovered code is uncovered", () => {
    for (const [code, reason] of OUT_OF_SCOPE) {
      expect(reason.length).toBeGreaterThan(0);
      // If one of these ever gains copy, the exemption should be deleted.
      expect(hasCopy(code)).toBe(false);
    }
  });

  it("never shows a raw code to a person", () => {
    for (const code of codes) {
      const message = messageFor(new ApiError(400, { code, detail: "internal wording" }));
      expect(message).not.toContain(code);
      expect(message).not.toMatch(/^[a-z0-9_]+$/);
    }
  });

  it("falls back to the server's detail for an unknown code", () => {
    const err = new ApiError(400, { code: "brand_new_thing", detail: "Something specific" });
    expect(messageFor(err)).toBe("Something specific");
  });

  it("never distinguishes a wrong password from an unknown account", () => {
    const unknown = new ApiError(401, { detail: "invalid credentials" });
    const wrong = new ApiError(401, { detail: "user not found" });
    expect(messageFor(unknown)).toBe(messageFor(wrong));
  });

  it("appends the correlation id only where one exists", () => {
    const withRef = new ApiError(500, { detail: "boom" }, "0123abcd-0000-4000-8000-000000000000");
    expect(messageWithRef(withRef)).toContain("ref 0123abcd");
    expect(messageWithRef(new ApiError(500, { detail: "boom" }))).not.toContain("ref");
  });

  it("reads attempts_left off the problem extras", () => {
    expect(attemptsLeft(new ApiError(400, { code: "code_invalid", attempts_left: 3 }))).toBe(3);
    expect(attemptsLeft(new ApiError(400, { code: "code_invalid" }))).toBeNull();
  });
});
