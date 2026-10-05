// Machine code → something a person can act on.
//
// The server's `detail` is written for a developer reading a log
// ("confirm it is you before making this change"); these are written for
// somebody who is locked out and getting cross. Every code listed in
// `docs/api/error-codes.md` that any IDX-W1 flow can raise has an entry —
// `tests/errorCopy.test.ts` reads that file and fails if one is missing,
// so a new server code cannot ship as a raw string in the UI.
//
// Codes that belong to flows this sprint does not build (`/auth/oauth/*`
// device grants, note-service model errors, MFA enrolment, account
// deletion) are listed in the test's exempt set with the reason, not
// silently ignored.

import { ApiError } from "../api/http";

/** Written in the second person, no jargon, and never a code number. */
const COPY: Record<string, string> = {
  // ── billing (0068) ────────────────────────────────────────────────
  billing_not_connected: "Payments aren't connected yet, so the plan can't change here.",
  redeem_unknown: "That code isn't valid. Check it and try again.",
  redeem_expired: "That code has expired.",
  redeem_used_up: "That code has already been used as many times as it allows.",
  redeem_already: "This workspace has already used that code.",
  redeem_rate_limited: "Too many tries. Wait a while and try again.",
  plan_contact_sales: "Enterprise is arranged with us — get in touch and we'll set it up.",
  // ── session ───────────────────────────────────────────────────────
  auth_refresh_replay:
    "You were signed out for security. Sign in again — if you did not expect this, change your password.",
  session_expired: "Your session ended. Sign in again to pick up where you left off.",
  no_refresh_token: "Your session ended. Sign in again.",
  session_revoked: "This session was ended somewhere else. Sign in again.",
  account_disabled: "This account has been disabled. Ask a workspace owner to re-enable it.",
  no_workspace: "This account is not in a workspace yet. Ask for an invitation, or contact support.",
  not_a_member: "You are not a member of that workspace.",
  membership_suspended: "Your access to that workspace is suspended.",
  // Distinct from not_a_member on purpose (IDX-M2): the caller WAS one,
  // so "you are not a member" would read as an error on their side.
  tenant_dissolved: "That workspace has been closed.",
  origin_not_allowed: "This page is not allowed to sign in. Open the app from its usual address.",

  // ── emailed codes ─────────────────────────────────────────────────
  invalid_email: "That does not look like an email address.",
  rate_limited: "Too many attempts. Wait a moment and try again.",
  rate_limiter_unavailable: "Sign-in is briefly unavailable. Try again in a minute.",
  email_delivery_unavailable: "We could not send the email just now. Try again in a moment.",
  code_invalid: "That code is not right.",
  challenge_expired: "That code has expired. Ask for a new one.",
  challenge_consumed: "That code has already been used. Ask for a new one.",
  too_many_attempts: "Too many wrong codes. Start again to get a new one.",
  // Not a failure — the code was right. The sentence has to explain a
  // redirect, not apologise for one, or people assume they typed it wrong.
  use_password: "This account signs in with a password. Enter it below to continue.",
  // `dual` mode: a Keycloak-issued session cannot be re-minted for another
  // workspace, so the switcher is off rather than broken. The sentence
  // names the way out, because "not available" alone is a dead end.
  legacy_session: "Switching workspaces needs a newer sign-in. Sign out and sign in with an emailed code.",

  // ── self-serve signup (BE-0) ──────────────────────────────────────
  // `signup_rate_limited` fails closed on purpose, so this can also mean
  // "the limiter is down" — the sentence has to hold for both.
  signup_rate_limited: "Too many sign-up attempts. Wait a few minutes and try again.",
  // The specifics live in `reasons[]`; the form lists them under the field
  // rather than stuffing them into one sentence.
  password_policy: "Please choose a stronger password.",
  display_name_required: "Please tell us your name.",
  // The endpoint compensates, so "nothing was created" is a promise the
  // server keeps, not reassurance we invented.
  signup_unavailable: "We could not create your account just now. Nothing was saved — try again in a moment.",
  // The code was right and the challenge was NOT spent, which is the only
  // reason it is safe to say "try again" instead of "ask for a new one".
  verify_retry: "Almost there — something on our side is briefly down. Your code still works; try again in a moment.",
  email_not_verified: "Confirm your email address first — we sent you a 6-digit code.",

  // ── password ──────────────────────────────────────────────────────
  otp_required: "Enter the code from your authenticator app.",
  otp_invalid: "That authenticator code is not right.",
  otp_unavailable: "We cannot check your second factor right now. Try again shortly.",
  mfa_enrolment_required: "Set up two-factor authentication before you can continue.",
  invalid_reset_token: "This reset link is no longer valid. Ask for a new one.",
  invalid_lockdown_token: "This security link is no longer valid. Reset your password instead.",
  password_breached:
    "That password has appeared in a known data breach. Please choose a different one.",

  // ── step-up ───────────────────────────────────────────────────────
  reauth_required: "Confirm it is you before making this change.",
  challenge_required: "Start the check again — we need a fresh code.",

  // ── room devices (IDX-B1b, surfaced by W2's devices screen) ───────
  rotation_in_progress:
    "This device already has two live secrets. Deploy or expire one before rotating again.",
  personal_workspace:
    "A personal workspace has no meeting room. Create a team workspace to add devices.",

  // ── account ───────────────────────────────────────────────────────
  email_in_use: "Another account already signs in with that address.",
  email_unchanged: "That is already your address.",
  mfa_already_enabled: "Two-factor authentication is already on for this account.",
  mfa_not_enabled: "Two-factor authentication is not set up for this account.",
  owner_reset_requires_owner: "Only another owner can reset an owner's second factor.",
  sole_owner_with_members:
    "You are the only owner of a workspace other people are still using. Hand it over first.",
  confirm_required: "Type DELETE to confirm.",

  // ── speaker count / re-labelling (Sprint 29) ──────────────────────
  // The roster maps these with sharper, in-place wording (RELABEL_COPY in
  // SpeakerRoster.tsx); these are the fallbacks any other surface gets.
  speakers_hint_invalid: "The number of people cannot be larger than the maximum.",
  job_not_complete: "The transcript is not finished yet. Try again when it is.",
  rediarize_in_progress: "Speakers are already being re-labelled.",
  audio_unavailable: "The recording is no longer kept, so speakers cannot be re-labelled.",
  rediarize_limit: "This transcript has been re-labelled as often as it can be.",
  enqueue_failed: "We could not start that just now. Nothing changed — try again in a moment.",
  nothing_to_undo: "There is nothing to undo any more.",
  // Sprint 31 dual-channel capture (sent by the macOS app only).
  channel_layout_mismatch: "This recording could not be read as a call recording. Try uploading it again.",
  local_speaker_name_invalid: "Your display name is too long to label your voice. Shorten it in your profile.",

  // ── moving turns / capture context (Sprint 30) ────────────────────
  // `stale_result_rev` is the one the transcript acts on: it reloads and
  // says this, so the sentence has to hold after the reload too.
  stale_result_rev: "Speakers were updated elsewhere.",
  bad_segment_index: "That part of the transcript has changed. Reload and try again.",
  too_many_segments: "That is too much to move at once. Move fewer turns at a time.",
  too_many_speakers: "A transcript can have at most 8 speakers. Move these turns to someone already listed.",
  unknown_label: "That speaker is no longer in this transcript. Reload and try again.",
  name_candidates_invalid: "The invited people's names could not be used. Record without them, or try again.",

  // ── note writing (Sprint 37 / L2) ─────────────────────────────────
  // The same three sentences GenerationStatus shows in its banner, so a
  // refused "Generate summary" reads the same as a run that never started.
  processor_unacknowledged:
    "A workspace admin has to agree to who processes your meetings before notes are written. Settings › Data & AI.",
  generation_disabled: "Automatic note writing is off for this workspace.",
  budget_exceeded:
    "This workspace has used its AI budget for the month, so this note was not written up. Your recording and your own notes are untouched.",
  generation_in_progress: "This note is already being written.",
  too_many_generations: "This note has been rewritten as often as it can be today.",
  no_transcript: "This note was not made from a recording, so there is nothing to write it from.",
  note_cancelled: "This note was cancelled and cannot be written again.",
  // Sprint 36: a 1:1 or an interview debrief has no version for a client.
  not_available_for_type: "A one-to-one and an interview debrief have no client version.",
};

/** The one sentence for a connection that never reached the server. */
export const OFFLINE_COPY = "Can't connect. Check your connection and try again.";

/** What an unmapped refusal says: by status, never the server's own words. */
function fallbackFor(status: number): string {
  if (status === 401) return "Incorrect email or password.";
  if (status === 403) return "You are not allowed to do that here.";
  if (status === 404) return "That could not be found. It may have been removed.";
  if (status === 409 || status === 412) return "That changed in the meantime. Reload and try again.";
  if (status === 413) return "That is too large to send.";
  if (status === 422) return "Something in what you entered is not right. Check it and try again.";
  if (status === 423) return "This account is temporarily locked. Try again shortly.";
  if (status === 429) return "Too many attempts. Wait a moment and try again.";
  if (status >= 500) return "The server had a problem. Try again in a moment.";
  return "Something went wrong. Try again in a moment.";
}

/** True when the code has a written message (what the coverage test asks). */
export function hasCopy(code: string): boolean {
  return code in COPY;
}

/**
 * The message to show for any thrown value.
 *
 * A code with copy gets its sentence; a role denial gets the one about
 * access; anything else gets a sentence for its status. The server's
 * `detail` is never shown: it is written for a developer reading a log,
 * and a raw "a workspace admin has to agree to who processes your
 * meetings [processor_unacknowledged]" is exactly what this file exists
 * to prevent. Somebody who has to quote the failure gets the ref from
 * `messageWithRef`.
 */
export function messageFor(err: unknown): string {
  if (!(err instanceof ApiError)) {
    if (err instanceof TypeError) return OFFLINE_COPY;
    if (err instanceof DOMException && err.name === "AbortError") return "That was cancelled.";
    // A plain Error is one of ours (a guard in a hook, a validation
    // sentence), written to be read.
    return err instanceof Error && err.message ? err.message : "Something went wrong. Try again in a moment.";
  }
  const written = err.code ? COPY[err.code] : undefined;
  if (written) return written;
  if (err.isRoleDenial) {
    return "This account is not allowed to do that in this workspace. Ask whoever runs it to give you access.";
  }
  return fallbackFor(err.status);
}

/**
 * The same message with the correlation id appended, for the cases where
 * somebody may have to quote it. Deliberately not used everywhere: a
 * wrong verification code is not a support ticket.
 */
export function messageWithRef(err: unknown): string {
  const base = messageFor(err);
  const ref = err instanceof ApiError ? err.requestId : undefined;
  return ref ? `${base} (ref ${ref.slice(0, 8)})` : base;
}

/** How long to wait, when the server said. */
export function retryAfterSeconds(err: unknown): number | null {
  return err instanceof ApiError ? (err.retryAfter ?? null) : null;
}

/**
 * The `reasons[]` a `password_policy` refusal carries, in sentences.
 *
 * Mirrors `domain/password_policy.py`, which returns codes rather than
 * prose precisely so the wording lives here. A code with no entry falls
 * through silently — the banner above the list already says the password
 * was refused, and inventing a sentence for a rule we do not know would
 * be worse than saying nothing.
 */
export function passwordReasons(err: unknown): string[] {
  if (!(err instanceof ApiError)) return [];
  const codes = err.extra<unknown>("reasons");
  if (!Array.isArray(codes)) return [];
  const min = err.extra<number>("min_length");
  const written: Record<string, string> = {
    too_short: `Use at least ${typeof min === "number" ? min : 12} characters.`,
    too_long: "That is longer than 128 characters.",
    common: "That one is near the top of every attacker's list.",
    contains_identifier: "It should not contain your name or email address.",
    repeated: "One character over and over is not a password.",
    sequential: "Avoid runs like abcde or 12345.",
    whitespace_only: "A password of only spaces will not do.",
  };
  return codes.map((c) => (typeof c === "string" ? written[c] : undefined)).filter(
    (line): line is string => Boolean(line),
  );
}

/** `attempts_left` on a wrong emailed code, when the server sends it. */
export function attemptsLeft(err: unknown): number | null {
  if (!(err instanceof ApiError)) return null;
  const n = err.extra<number>("attempts_left");
  return typeof n === "number" ? n : null;
}
