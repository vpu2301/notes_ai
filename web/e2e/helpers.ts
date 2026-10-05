import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, type Page } from "@playwright/test";

// ESM specs: no `__dirname`.
const HERE = dirname(fileURLToPath(import.meta.url));
const MAILPIT_READER = resolve(HERE, "../../scripts/ci/mailpit-last-code.py");

/** A fresh address; `.test` (RFC 6761) can never resolve, so a leaked send bounces. */
export function freshEmail(prefix = "first-use"): string {
  // Digits only: `/welcome` drops digit words from the name suggestion, so it stays "First Use".
  const stamp = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  return `${prefix}-${stamp}@example.test`;
}

/** The sign-in code Mailpit received for `email`, via the same script the CI gate uses. */
export function codeFor(email: string, waitSeconds = 25): string {
  try {
    return execFileSync("python3", [MAILPIT_READER, email, "--wait", String(waitSeconds)], {
      encoding: "utf8",
      timeout: (waitSeconds + 10) * 1000,
    }).trim();
  } catch (err) {
    const status = (err as { status?: number }).status;
    if (status === 2) {
      throw new Error(
        "Mailpit is not answering on :8025. Bring the stack up with `make web-e2e-stack` " +
          "— auth-service must run with MDX_IDP_MODE=native and MDX_AUTH_SMTP_HOST=mailpit.",
      );
    }
    throw new Error(`no sign-in code arrived for ${email} within ${waitSeconds}s`);
  }
}

/** Pastes a six-digit code into the first box (exercises the spread-across-boxes path); it submits on its own. */
export async function enterCode(page: Page, code: string): Promise<void> {
  await page.getByRole("group", { name: /sign-in code/i }).getByRole("textbox").first().click();
  await page.keyboard.insertText(code);
}

/** The page's own "New meeting", not the sidebar's. */
export function newMeetingButton(page: Page) {
  return page.getByRole("group", { name: /start a note/i }).getByRole("button", { name: /new meeting/i });
}

/** Sign up (or in) with an emailed code; the caller asserts on the destination. */
export async function signInWithCode(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(email);
  await page.getByRole("button", { name: /email me a code/i }).click();
  await expect(page.getByText(/check your email/i)).toBeVisible();
  await enterCode(page, codeFor(email));
}

/** `GET /auth/me` as the signed-in browser sees it. */
export async function fetchMe(page: Page): Promise<{
  identity: { email: string } | null;
  memberships: { kind: string; role: string }[];
}> {
  return page.evaluate(async () => {
    // The bearer lives in a closure; mint a fresh one from the refresh cookie.
    const base = "http://localhost:8000";
    const refreshed = await fetch(`${base}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "X-Client-Type": "web" },
    });
    const { access_token } = (await refreshed.json()) as { access_token: string };
    const res = await fetch(`${base}/auth/me`, {
      credentials: "include",
      headers: { Authorization: `Bearer ${access_token}`, "X-Client-Type": "web" },
    });
    return res.json();
  });
}

/**
 * Records every URL the router puts in the address bar, in order. Hooks `history`
 * because `framenavigated` does not reliably report same-document navigations.
 * Call before the first `goto`.
 */
export async function trackScreens(page: Page): Promise<() => Promise<string[]>> {
  await page.addInitScript(() => {
    const seen: string[] = [];
    const note = () => {
      const path = location.pathname;
      if (seen[seen.length - 1] !== path) seen.push(path);
    };
    for (const name of ["pushState", "replaceState"] as const) {
      const original = history[name];
      history[name] = function (this: History, ...args: Parameters<History["pushState"]>) {
        const result = original.apply(this, args);
        note();
        return result;
      };
    }
    addEventListener("popstate", note);
    note();
    (window as unknown as { __screens: string[] }).__screens = seen;
  });
  return () => page.evaluate(() => (window as unknown as { __screens: string[] }).__screens);
}

/** No screen on the way in may ask for a password. */
export async function expectNoPasswordField(page: Page): Promise<void> {
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
}
