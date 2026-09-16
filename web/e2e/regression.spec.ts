import { expect, test } from "@playwright/test";
import { codeFor, enterCode, freshEmail } from "./helpers";

/**
 * WEB-1b §4 — what the emailed code must not have broken.
 *
 * `dual` mode is the whole point of this sprint's risk: a deployment where
 * some accounts are native and some are still Keycloak's, and where the
 * new way in must not become the only way in. These are the two seeded
 * accounts that prove the old ones still work.
 *
 * Both are skipped rather than failed when their fixture is absent —
 * `E2E_PASSWORD_EMAIL` unset means this stack is native-only, which is a
 * legitimate configuration and not a regression.
 */

const PASSWORD_EMAIL = process.env.E2E_PASSWORD_EMAIL;
const PASSWORD = process.env.E2E_PASSWORD ?? "dev-password";
const MFA_EMAIL = process.env.E2E_MFA_EMAIL;

test.describe("password sign-in still works", () => {
  test.skip(!PASSWORD_EMAIL, "no seeded password account (E2E_PASSWORD_EMAIL)");

  test("a seeded account signs in at /login/password", async ({ page }) => {
    await page.goto("/login/password");
    await page.getByLabel(/^email$/i).fill(PASSWORD_EMAIL!);
    await page.getByLabel(/^password$/i).fill(PASSWORD);
    await page.getByRole("button", { name: /^sign in$/i }).click();

    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("group", { name: /start a note/i })).toBeVisible();
  });

  test("the code screen offers the password form without losing the address", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/email/i).fill(PASSWORD_EMAIL!);
    await page.getByRole("link", { name: /use a password instead/i }).click();

    // Carried across, so switching methods is not a retype.
    await expect(page.getByLabel(/^email$/i)).toHaveValue(PASSWORD_EMAIL!);
    await expect(page.getByLabel(/^password$/i)).toBeFocused();
  });
});

test.describe("a second factor is still asked for", () => {
  test.skip(!MFA_EMAIL, "no seeded MFA account (E2E_MFA_EMAIL)");

  test("the code step hands an MFA account to /login/mfa", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/email/i).fill(MFA_EMAIL!);
    await page.getByRole("button", { name: /email me a code/i }).click();
    await enterCode(page, codeFor(MFA_EMAIL!));

    // The right code does not buy a session on its own — that is the whole
    // contract of `status: "mfa_required"`, and landing on `/` here would
    // mean the second factor had quietly stopped mattering.
    await expect(page).toHaveURL(/\/login\/mfa$/);
    await expect(page.getByLabel(/authenticator code/i)).toBeVisible();
  });
});

test("an unknown address is indistinguishable from a known one", async ({ page }) => {
  // The enumeration property, asserted from the outside: the screen after
  // "email me a code" says the same thing either way. A future edit that
  // helpfully says "we don't know that address" fails here.
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(freshEmail("never-seen"));
  await page.getByRole("button", { name: /email me a code/i }).click();

  await expect(page.getByText(/check your email/i)).toBeVisible();
  await expect(page.getByText(/if .* is a valid address/i)).toBeVisible();
  await expect(page.getByText(/no account|not found|unknown/i)).toHaveCount(0);
});
