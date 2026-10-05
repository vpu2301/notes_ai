// The auth-service surface the web client uses.
// Invariants: `credentials: true` on `/auth/*` (the refresh token lives only in
// the HttpOnly `mdx_rt` cookie; never read `refresh_token` from a body), and
// `auth: false` on signed-out calls so a 401 does not trigger a silent refresh.
// Native-only routes (`/auth/email/*`, `/auth/mfa/*`, `/auth/reauth*`, `PATCH
// /auth/me`) and keycloak-only `/auth/password/*` answer 404 when unmounted.

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

/** A 404 from a mode-specific route means "this deployment does not serve that flow". */
export function isUnavailableHere(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

// ── email one-time code: signup and login on one path ──────────────────

/** Always 202 for a valid address — known/unknown are indistinguishable by design. */
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

// ── self-serve signup (keycloak and dual modes) ───────────────────────

export interface SignupBody {
  email: string;
  password: string;
  display_name: string;
  /** Referral code a shared note's CTA carried into `/join`. */
  ref?: string;
}

export function signupConfig(): Promise<SignupConfig> {
  return api<SignupConfig>("auth", "/auth/signup/config", { auth: false });
}

/** 202 whether or not the address has an account — not an enumeration oracle; the UI must not claim a code is on its way. */
export function signup(body: SignupBody): Promise<SignupAccepted> {
  return api<SignupAccepted>("auth", "/auth/signup", {
    method: "POST",
    json: body,
    auth: false,
  });
}

/** No session comes back; the caller signs in afterwards. */
export function signupVerify(email: string, code: string): Promise<{ verified: true }> {
  return api<{ verified: true }>("auth", "/auth/signup/verify", {
    method: "POST",
    json: { email, code },
    auth: false,
  });
}

/** 202 whether or not there was anything to send. */
export function signupResend(email: string): Promise<SignupAccepted> {
  return api<SignupAccepted>("auth", "/auth/signup/resend", {
    method: "POST",
    json: { email },
    auth: false,
  });
}

// ── password (Keycloak-backed) ────────────────────────────────────────

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

/** `token` comes from the mailed link's fragment; a rejected password does not burn it. */
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

// ── second factor ─────────────────────────────────────────────────────

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

// ── step-up ───────────────────────────────────────────────────────────

/** The server chooses the methods; the client cannot pick a weaker one. */
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

/** Fake door: the address left on `/join`. No session, no mail. */
export function captureLead(email: string, ref: string | null): Promise<{ status: "accepted" }> {
  return api<{ status: "accepted" }>("auth", "/auth/leads", {
    method: "POST",
    json: { email, ref: ref || undefined, consent: true },
    auth: false,
  });
}
