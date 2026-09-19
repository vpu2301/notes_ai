// The auth-service surface the web client uses (IDX-W1 §G).
//
// Two things every function here honours, and neither is optional:
//
//  * `credentials: true` on `/auth/*`, because the refresh token lives in
//    the HttpOnly `mdx_rt` cookie and nowhere else. Nothing in this file
//    reads a `refresh_token` out of a response body — that field is for
//    macOS and iOS, and a browser that parsed it would be putting a
//    long-lived credential into JavaScript's reach.
//  * `auth: false` on anything a signed-out person calls, so the wrapper
//    does not attempt a silent refresh on a 401 that simply means
//    "wrong code".
//
// Mode note: `/auth/email/*`, `/auth/mfa/*` (native), `/auth/reauth*` and
// `PATCH /auth/me` are mounted only under `MDX_IDP_MODE=native`, and
// `/auth/password/*` only under `keycloak`. The unmounted half answers 404
// by design, so a prober cannot tell a switched-off feature from an absent
// one — `isUnavailableHere` is how the UI tells the difference.

import { ApiError, api } from "./http";
import type {
  AuthResult,
  EmailChallenge,
  Identity,
  LockdownResult,
  LoginResponse,
  MeResponse,
  MfaMethod,
  PasswordPolicy,
  ReauthOptions,
  SignupAccepted,
  SignupConfig,
} from "./types";

/**
 * A 404 from a native-only or keycloak-only route means "this deployment
 * does not serve that flow", not "you asked for something that is gone".
 * See `docs/api/error-codes.md`, closing note.
 */
export function isUnavailableHere(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

// ── email one-time code: signup and login on one path (IDX-A3) ─────────

/**
 * Always 202 for a syntactically valid address — known, unknown, locked
 * and undeliverable are indistinguishable by construction. Do not write UI
 * that implies otherwise.
 */
export function emailStart(email: string): Promise<EmailChallenge> {
  return api<EmailChallenge>("auth", "/auth/email/start", {
    method: "POST",
    json: { email },
    auth: false,
    credentials: true,
  });
}

export function emailVerify(challengeId: string, code: string): Promise<AuthResult> {
  return api<AuthResult>("auth", "/auth/email/verify", {
    method: "POST",
    json: { challenge_id: challengeId, code },
    auth: false,
    credentials: true, // the 200 carries the refresh cookie
  });
}

// ── self-serve signup (BE-0, keycloak and dual modes) ─────────────────

export interface SignupBody {
  email: string;
  password: string;
  display_name: string;
  /** Sprint 21: the referral code a shared note's CTA carried into `/join`. */
  ref?: string;
}

/**
 * Create an account. Answers 202 for an address that already has one, and
 * for one that does not — the reply is byte-identical either way, so this
 * endpoint is not a "does X have an account here?" oracle. The screen that
 * calls it must not claim a code is on its way; only that one is if the
 * address is new.
 *
 * Refusals that *are* the caller's to see: `invalid_email`,
 * `display_name_required`, `password_policy` (with `min_length` and
 * `reasons[]`), `signup_rate_limited`, `signup_unavailable`.
 */
export function signupConfig(): Promise<SignupConfig> {
  return api<SignupConfig>("auth", "/auth/signup/config", { auth: false });
}

export function signup(body: SignupBody): Promise<SignupAccepted> {
  return api<SignupAccepted>("auth", "/auth/signup", {
    method: "POST",
    json: body,
    auth: false,
  });
}

/**
 * Spend the mailed code and enable the account. No session comes back —
 * `verified: true` is the whole body — so the caller signs in afterwards.
 */
export function signupVerify(email: string, code: string): Promise<{ verified: true }> {
  return api<{ verified: true }>("auth", "/auth/signup/verify", {
    method: "POST",
    json: { email, code },
    auth: false,
  });
}

/**
 * Another code. Unauthenticated by necessity: the person who needs this
 * cannot sign in, which is the problem. 202 whether or not there was
 * anything to send, for the same reason `signup` is.
 */
export function signupResend(email: string): Promise<SignupAccepted> {
  return api<SignupAccepted>("auth", "/auth/signup/resend", {
    method: "POST",
    json: { email },
    auth: false,
  });
}

// ── password (Keycloak-backed until IDX-A4) ───────────────────────────

export function login(email: string, password: string, otp?: string): Promise<LoginResponse> {
  return api<LoginResponse>("auth", "/auth/login", {
    method: "POST",
    json: otp ? { email, password, otp } : { email, password },
    auth: false,
    credentials: true,
  });
}

export function passwordPolicy(): Promise<PasswordPolicy> {
  return api<PasswordPolicy>("auth", "/auth/password/policy", { auth: false });
}

/** Always 202, for the same enumeration reason as `emailStart`. */
export function passwordForgot(email: string): Promise<void> {
  return api<void>("auth", "/auth/password/forgot", {
    method: "POST",
    json: { email },
    auth: false,
  });
}

/**
 * `token` comes from the mailed link's fragment, never from a form. The
 * server peeks before it consumes, so a rejected password does not burn
 * the link — a second attempt with a stronger one still works.
 */
export function passwordReset(token: string, newPassword: string): Promise<void> {
  return api<void>("auth", "/auth/password/reset", {
    method: "POST",
    json: { token, new_password: newPassword },
    auth: false,
  });
}

/** "This wasn't me": ends every session and hands back a fresh reset token. */
export function accountLockdown(token: string): Promise<LockdownResult> {
  return api<LockdownResult>("auth", "/auth/security/lockdown", {
    method: "POST",
    json: { token },
    auth: false,
  });
}

// ── second factor (IDX-A5) ────────────────────────────────────────────

/** Unauthenticated by design — the caller has no session yet. */
export function mfaVerify(
  challengeId: string,
  method: MfaMethod,
  code: string,
): Promise<AuthResult> {
  return api<AuthResult>("auth", "/auth/mfa/verify", {
    method: "POST",
    json: { challenge_id: challengeId, method, code },
    auth: false,
    credentials: true,
  });
}

// ── step-up (IDX-A5) ──────────────────────────────────────────────────

/**
 * The server chooses the methods: an MFA account is asked for its
 * authenticator, everyone else is mailed a code (and gets the
 * `challenge_id` to quote back). The client does not get to pick the
 * weaker one.
 */
export function reauthStart(): Promise<ReauthOptions> {
  return api<ReauthOptions>("auth", "/auth/reauth/start", { method: "POST" });
}

export function reauth(
  method: "totp" | "recovery_code" | "email_code",
  code: string,
  challengeId?: string | null,
): Promise<void> {
  return api<void>("auth", "/auth/reauth", {
    method: "POST",
    json: challengeId ? { method, code, challenge_id: challengeId } : { method, code },
  });
}

// ── session & profile ─────────────────────────────────────────────────

export function logout(): Promise<void> {
  return api<void>("auth", "/auth/logout", { method: "POST", credentials: true });
}

export function fetchMe(): Promise<MeResponse> {
  return api<MeResponse>("auth", "/auth/me");
}

export interface ProfilePatch {
  display_name?: string;
  locale?: "en" | "de" | "uk";
  timezone?: string;
}

/** Returns the updated `IdentitySummary`. Not gated on recent auth. */
export function patchMe(patch: ProfilePatch): Promise<Identity> {
  return api<Identity>("auth", "/auth/me", { method: "PATCH", json: patch });
}

/**
 * Sprint 19 fake door: the address left on `/join`. No session, no mail —
 * the row is the whole result. `ref` is the code the shared page's CTA
 * carried over (absent for a public link's CTA).
 */
export function captureLead(email: string, ref: string | null): Promise<{ status: "accepted" }> {
  return api<{ status: "accepted" }>("auth", "/auth/leads", {
    method: "POST",
    json: { email, ref: ref || undefined, consent: true },
    auth: false,
  });
}
