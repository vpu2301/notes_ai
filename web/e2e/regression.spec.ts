import { expect, test, type Browser, type Page } from "@playwright/test";
import { codeFor, enterCode, freshEmail, signInWithCode } from "./helpers";

/**
 * Password and MFA sign-in still work beside the emailed code (`dual` mode).
 * Skipped, not failed, when the seeded fixture is absent (native-only stack).
 */

const PASSWORD_EMAIL = process.env.E2E_PASSWORD_EMAIL;
const PASSWORD = process.env.E2E_PASSWORD ?? "dev-password";
const MFA_EMAIL = process.env.E2E_MFA_EMAIL;
/** An account with at least two workspaces (W1 has no "New workspace" yet, so it is seeded). */
const TWO_WORKSPACE_EMAIL = process.env.E2E_TWO_WORKSPACE_EMAIL;

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

    // The address is carried across.
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

    // `status: "mfa_required"` must not yield a session on its own.
    await expect(page).toHaveURL(/\/login\/mfa$/);
    await expect(page.getByLabel(/authenticator code/i)).toBeVisible();
  });
});

test("an unknown address is indistinguishable from a known one", async ({ page }) => {
  // No account enumeration: the screen reads the same either way.
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(freshEmail("never-seen"));
  await page.getByRole("button", { name: /email me a code/i }).click();

  await expect(page.getByText(/check your email/i)).toBeVisible();
  await expect(page.getByText(/if .* is a valid address/i)).toBeVisible();
  await expect(page.getByText(/no account|not found|unknown/i)).toHaveCount(0);
});

test.describe("two tabs share one session", () => {
  test.skip(!TWO_WORKSPACE_EMAIL, "no seeded two-workspace account (E2E_TWO_WORKSPACE_EMAIL)");

  test("the tab that did not switch refuses writes until it follows", async ({ context }) => {
    const first = await context.newPage();
    await signInWithCode(first, TWO_WORKSPACE_EMAIL!);
    await expect(first.getByRole("group", { name: /start a note/i })).toBeVisible();

    // Same cookie jar: the second tab restores the same session.
    const second = await context.newPage();
    await second.goto("/");
    await expect(second.getByRole("group", { name: /start a note/i })).toBeVisible();

    // Switch in the first tab to whichever workspace is not current.
    await first.locator(".sb-ws").click();
    const target = first.getByRole("menuitemradio", { checked: false }).first();
    const targetName = (await target.locator(".grow").innerText()).trim();
    await target.click();
    await expect(first.locator(".sb-ws")).toContainText(targetName);

    // The second tab hears it at once and will not write into either workspace.
    const strip = second.getByRole("status").filter({ hasText: /in another tab/i });
    await expect(strip).toContainText(targetName);
    await second.keyboard.press("b");
    await expect(second).not.toHaveURL(/\/notes\//);

    // One click follows the session.
    await strip.getByRole("button", { name: /continue there/i }).click();
    await expect(strip).toHaveCount(0);
    await expect(second.locator(".sb-ws")).toContainText(targetName);
  });
});

/**
 * Two people, two browser contexts (separate cookie jars). Both accounts must exist and be past
 * `/welcome`; each signs in with an emailed code read from Mailpit.
 */
const INVITER_EMAIL = process.env.E2E_INVITER_EMAIL;
const INVITEE_EMAIL = process.env.E2E_INVITEE_EMAIL;

/** The inviter makes a workspace and invites the invitee, who accepts from `/invitations`. */
async function workspaceWithInvitee(browser: Browser, name: string): Promise<{ inviter: Page; invitee: Page }> {
  const inviter = await (await browser.newContext()).newPage();
  await signInWithCode(inviter, INVITER_EMAIL!);
  await inviter.locator(".sb-ws").click();
  await inviter.getByRole("menuitem", { name: "New workspace…" }).click();
  await inviter.getByRole("textbox", { name: "Name" }).fill(name);
  await inviter.keyboard.press("Enter");
  await expect(inviter).toHaveURL(/\/settings\/members\?first=1$/);
  await expect(inviter.locator(".sb-ws")).toContainText(name);

  await inviter.getByRole("textbox", { name: "Email", exact: true }).fill(INVITEE_EMAIL!);
  await inviter.getByRole("button", { name: "Invite", exact: true }).click();
  await expect(inviter.getByLabel("Invitation results")).toContainText("Sent");
  await expect(inviter.getByLabel("Pending invitations")).toContainText(INVITEE_EMAIL!);

  const invitee = await (await browser.newContext()).newPage();
  await signInWithCode(invitee, INVITEE_EMAIL!);
  await invitee.goto("/invitations");
  const row = invitee.locator(".row").filter({ hasText: name });
  await row.getByRole("button", { name: "Accept" }).click();
  await expect(invitee.locator(".sb-ws")).toContainText(name);
  await expect(invitee.getByText(`You joined ${name}`)).toBeVisible();
  return { inviter, invitee };
}

test.describe("workspaces and sharing between two people", () => {
  test.skip(!INVITER_EMAIL || !INVITEE_EMAIL, "no two seeded accounts (E2E_INVITER_EMAIL, E2E_INVITEE_EMAIL)");

  test("create workspace → invite → accept in a second context", async ({ browser }) => {
    const name = `Sunrise ${Date.now()}`;
    const { inviter } = await workspaceWithInvitee(browser, name);

    // The inviter's roster now has the invitee, and the invitation is no longer pending.
    await inviter.reload();
    await expect(inviter.getByText(INVITEE_EMAIL!)).toBeVisible();
    await expect(inviter.getByLabel("Pending invitations")).toHaveCount(0);
  });

  test("share as comment → second context cannot type, can comment", async ({ browser }) => {
    const { inviter, invitee } = await workspaceWithInvitee(browser, `Review ${Date.now()}`);

    // A private note, shared with one person who may only comment.
    await inviter.goto("/");
    await inviter.keyboard.press("b");
    await expect(inviter).toHaveURL(/\/notes\/[^/]+$/);
    const noteUrl = new URL(inviter.url()).pathname;
    await inviter.getByLabel("Note title").fill("Pricing review");
    await inviter.getByRole("button", { name: /more actions/i }).click();
    await inviter.getByRole("menuitem", { name: /share…/i }).click();
    const dialog = inviter.getByRole("dialog", { name: "Share note" });
    await dialog.getByRole("radiogroup", { name: "General access" }).getByRole("radio", { name: "Private" }).click();
    await dialog.getByLabel("Invite people").fill(INVITEE_EMAIL!);
    await dialog.getByRole("button", { name: "Role", exact: true }).click();
    await inviter.getByRole("menuitemradio", { name: /can comment/i }).click();
    await dialog.getByRole("button", { name: "Share", exact: true }).click();
    await expect(dialog.getByLabel("Share results")).toContainText(INVITEE_EMAIL!);
    await dialog.getByRole("button", { name: "Done" }).click();

    // The collaborator: a read-only note with a strip, and a comment box.
    const drafts: string[] = [];
    invitee.on("request", (r) => {
      if (r.method() === "PUT" && r.url().endsWith("/draft")) drafts.push(r.url());
    });
    await invitee.goto(noteUrl);
    await expect(invitee.getByText("You can comment on this note")).toBeVisible();
    const title = invitee.getByLabel("Note title");
    await expect(title).toHaveValue("Pricing review");
    await title.click({ force: true });
    await invitee.keyboard.type("typed");
    await expect(title).toHaveValue("Pricing review");
    await expect(invitee.getByRole("menuitem", { name: /share…/i })).toHaveCount(0);

    await invitee.getByRole("button", { name: /^comments/i }).click();
    const panel = invitee.getByRole("complementary", { name: "Comments" });
    await panel.getByLabel("Comment", { exact: true }).fill("Is the discount final?");
    await panel.getByRole("button", { name: "Comment", exact: true }).click();
    await expect(panel.getByText("Is the discount final?")).toBeVisible();
    expect(drafts).toEqual([]);
  });
});
