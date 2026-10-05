import { expect, test } from "@playwright/test";
import {
  expectNoPasswordField,
  fetchMe,
  freshEmail,
  newMeetingButton,
  signInWithCode,
  trackScreens,
} from "./helpers";

/**
 * One journey, deliberately not split per screen: a never-seen address to a note
 * that exists, with the session surviving every seam on the way.
 */
test("a stranger becomes a signed-in person with a note", async ({ page }) => {
  const email = freshEmail();
  const screens = await trackScreens(page);

  // ── sign up ────────────────────────────────────────────────────────
  await signInWithCode(page, email);

  // A new identity is asked its name, nothing else.
  await expect(page).toHaveURL(/\/welcome$/);
  await expectNoPasswordField(page);
  const nameBox = page.getByLabel(/your name/i);
  // Prefilled from the local part: digit words dropped, rest title-cased.
  await expect(nameBox).toHaveValue("First Use");
  await nameBox.fill("Alex Kim");
  await page.getByRole("button", { name: /continue/i }).click();

  // ── the empty workspace ────────────────────────────────────────────
  await expect(page).toHaveURL(/\/$/);
  await expectNoPasswordField(page);
  // The recorder has focus.
  await expect(newMeetingButton(page)).toBeFocused();
  await expect(page.getByRole("region", { name: /get started/i })).toBeVisible();
  // No calendar consent before there is a note.
  await expect(page.getByRole("button", { name: /connect google calendar/i })).toHaveCount(0);

  // ── the workspace signup created ───────────────────────────────────
  const me = await fetchMe(page);
  expect(me.identity?.email).toBe(email);
  expect(me.memberships[0]?.kind).toBe("personal");
  expect(me.memberships[0]?.role).toBe("owner");

  // ── record ─────────────────────────────────────────────────────────
  await newMeetingButton(page).click();
  await page.getByLabel(/meeting title/i).fill("First meeting");
  await page.getByRole("button", { name: /^record$/i }).click();

  // Two seconds of Chromium's fake audio: enough for a chunk and for the timer to move.
  await expect(page.getByText(/^00:0[1-9]$/)).toBeVisible({ timeout: 5_000 });
  await page.waitForTimeout(2_000);
  await page.getByRole("button", { name: /stop/i }).click();

  // ── the note ───────────────────────────────────────────────────────
  // Real transcription on purpose: a mocked ASR would not prove the job-to-note hand-off.
  await expect(page).toHaveURL(/\/notes\/[0-9a-f-]{36}$/, { timeout: 4 * 60_000 });
  await expect(page.getByLabel(/note title/i)).toHaveValue(/first meeting/i);

  // ── the shape of the path ──────────────────────────────────────────
  // ≤ 3 screens before the recorder; asserted on the list so a regression names the screen.
  const visited = await screens();
  const beforeRecorder = visited.slice(0, visited.indexOf("/meeting/new"));
  expect(beforeRecorder, `screens: ${visited.join(" → ")}`).toEqual([
    "/login",
    "/welcome",
    "/",
  ]);
});

test("a returning person skips /welcome", async ({ page, context }) => {
  const email = freshEmail("returning");

  await signInWithCode(page, email);
  await expect(page).toHaveURL(/\/welcome$/);
  await page.getByRole("button", { name: /skip for now/i }).click();
  await expect(page).toHaveURL(/\/$/);

  // Second sign-in, same address, no session.
  await context.clearCookies();
  await signInWithCode(page, email);

  // `is_new_identity` is false now, so no name question.
  await expect(page).toHaveURL(/\/$/);
  await expectNoPasswordField(page);
});
