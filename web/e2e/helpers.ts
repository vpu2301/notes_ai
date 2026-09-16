import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, type Page } from "@playwright/test";

// `web/package.json` is `"type": "module"`, so Playwright loads these specs
// as real ESM and `__dirname` does not exist. Derive it.
const HERE = dirname(fileURLToPath(import.meta.url));
const MAILPIT_READER = resolve(HERE, "../../scripts/ci/mailpit-last-code.py");

/**
 * A fresh address, unused by construction.
 *
 * `@example.test` because RFC 6761 reserves `.test` for exactly this and it
 * can never resolve — a fixture that leaks into a real send should bounce
 * rather than reach a stranger.
 */
export function freshEmail(prefix = "first-use"): string {
  // Digits only in the unique half, deliberately. `/welcome` prefills the
  // name box from the local part and drops any word containing a digit, so
  // a numeric stamp makes the suggestion predictable — `first-use-1725…`
  // is always "First Use" — and a test can assert on it exactly.
  const stamp = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  return `${prefix}-${stamp}@example.test`;
}

/**
 * The sign-in code Mailpit received for `email`.
 *
 * Shelling out to the FND-2 script rather than reimplementing the read:
 * one definition of "which mail is the code mail" means the CI gate and
 * these tests cannot disagree about it.
 */
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

/**
 * Types a six-digit code into the boxed input; it submits on its own.
 *
 * Into the FIRST box, as a single insert. That is a paste, which is how
 * most people move a code out of a mail client, and it is the path that
 * exercises the component's spread-across-six-boxes handling rather than
 * six independent keystrokes.
 */
export async function enterCode(page: Page, code: string): Promise<void> {
  await page.getByRole("group", { name: /sign-in code/i }).getByRole("textbox").first().click();
  await page.keyboard.insertText(code);
}

/** The page's own "New meeting", not the sidebar's. */
export function newMeetingButton(page: Page) {
  return page.getByRole("group", { name: /start a note/i }).getByRole("button", { name: /new meeting/i });
}

/**
 * Sign up (or in) with an emailed code, from `/login` to wherever the app
 * puts them next. Returns nothing: the caller asserts on the destination,
 * because "where does a new identity land" is the thing under test.
 */
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
    // The page's own transport holds the bearer in a closure, so the test
    // cannot borrow it. The refresh cookie is a cookie, though, so a fresh
    // access token is one call away — and using it proves the cookie is
    // doing its job, which is worth asserting anyway.
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
 * Records every URL the app puts in the address bar, in order.
 *
 * Hooking `history` rather than listening for Playwright's
 * `framenavigated`: React Router changes screens with `pushState` and
 * `replaceState`, which are same-document navigations, and how faithfully
 * a given Playwright version reports those is not something a claim about
 * "≤ 3 screens" should rest on. This counts what the router actually did.
 *
 * Must be called before the first `goto` — an init script runs on every
 * new document, but only from the point it is installed.
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
