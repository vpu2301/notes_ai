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
 * WEB-1b §3 — the batch's exit criterion.
 *
 * One test, one journey: an address the system has never seen, to a note
 * that exists. Everything it asserts is something a person would notice if
 * it broke — how many screens they pass, whether anything asks for a
 * password, whether the workspace they land in is their own.
 *
 * It is deliberately not decomposed into a screen each. The value here is
 * that the seams hold: the code step's session survives into `/welcome`,
 * `/welcome`'s `PATCH` does not cost the session, the recorder inherits
 * it, and the note that comes back belongs to the workspace signup made.
 * Four passing screen tests and a broken journey is the failure mode this
 * exists to catch.
 */
test("a stranger becomes a signed-in person with a note", async ({ page }) => {
  const email = freshEmail();
  const screens = await trackScreens(page);

  // ── sign up ────────────────────────────────────────────────────────
  await signInWithCode(page, email);

  // A brand-new identity is asked its name, and nothing else.
  await expect(page).toHaveURL(/\/welcome$/);
  await expectNoPasswordField(page);
  const nameBox = page.getByLabel(/your name/i);
  // Prefilled from the address's local part (WEB-1a §4): `first-use-<digits>`
  // loses the numeric word and title-cases the rest.
  await expect(nameBox).toHaveValue("First Use");
  await nameBox.fill("Alex Kim");
  await page.getByRole("button", { name: /continue/i }).click();

  // ── the empty workspace ────────────────────────────────────────────
  await expect(page).toHaveURL(/\/$/);
  await expectNoPasswordField(page);
  // The recorder has the caret: this is the last screen before the thing
  // they came for, and it should not need a hunt with the mouse.
  await expect(newMeetingButton(page)).toBeFocused();
  // One line and a call to action, not a list with nothing in it.
  await expect(page.getByRole("region", { name: /get started/i })).toBeVisible();
  // No calendar consent before there is a note to hang it on (§2).
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

  // Two seconds of Chromium's fake audio device. Long enough for
  // MediaRecorder to emit a chunk and for the timer to move off 00:00,
  // which is what tells us a stream is genuinely flowing.
  await expect(page.getByText(/^00:0[1-9]$/)).toBeVisible({ timeout: 5_000 });
  await page.waitForTimeout(2_000);
  await page.getByRole("button", { name: /stop/i }).click();

  // ── the note ───────────────────────────────────────────────────────
  // A real transcription of real (if synthetic) audio. Slow, and the point:
  // a mocked ASR would prove the upload and nothing about the hand-off that
  // turns a finished job into a note.
  await expect(page).toHaveURL(/\/notes\/[0-9a-f-]{36}$/, { timeout: 4 * 60_000 });
  await expect(page.getByLabel(/note title/i)).toHaveValue(/first meeting/i);

  // ── the shape of the path ──────────────────────────────────────────
  // "≤ 3 screens before the recorder": /login, /welcome, /. The recorder
  // itself is the fourth and is where they were going. Asserted on the
  // list rather than the count, so a regression says WHICH screen crept in.
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

  // Second sign-in, same address, no session carried over.
  await context.clearCookies();
  await signInWithCode(page, email);

  // `is_new_identity` is false this time, so the name question does not
  // come back — being asked twice is how a product looks like it forgot.
  await expect(page).toHaveURL(/\/$/);
  await expectNoPasswordField(page);
});
