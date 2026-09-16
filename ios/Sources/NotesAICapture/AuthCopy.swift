import Foundation

/// What a failed auth request says to the person holding the phone.
///
/// One map, keyed on the machine-readable `code` the server sends
/// (`docs/api/error-codes.md`), because the alternative — each screen
/// inventing its own wording from `detail` — produces a different
/// sentence for the same failure on every screen, and `detail` is
/// explicitly allowed to change.
///
/// Anything unrecognised falls through to a generic line **with the
/// request id**, which is the whole point of sending `X-Request-Id`: an
/// unknown failure the person can quote is one somebody can look up.
enum AuthCopy {
    static func message(for error: Error) -> String {
        guard let apiError = error as? APIError else { return error.localizedDescription }
        switch apiError {
        case .badURL, .notAuthenticated, .sessionRevoked, .sessionLocked,
             .reauthRequired, .malformedResponse, .noNativeSession:
            return apiError.errorDescription ?? "Something went wrong."
        case .http(let status, let problem):
            return message(status: status, problem: problem)
        }
    }

    static func message(status: Int, problem: Problem?) -> String {
        if let code = problem?.code, let known = copy(for: code, problem: problem) {
            return known
        }
        switch status {
        case 401:
            return "Wrong sign-in details."
        case 403:
            // `libs/auth`'s role gate answers `deny: roles=[…] cannot
            // 'note.read' on 'note'` — a sentence about the permission
            // matrix, not about the person reading it. `APIClient` has
            // already refreshed once by the time this is reached (roles
            // are re-read from the membership on every rotation), so what
            // is left is a real refusal worth naming plainly.
            if let detail = problem?.detail, detail.hasPrefix("deny:") {
                return "This account is not allowed to do that in this workspace. Ask whoever runs it to give you access."
            }
            return problem?.detail ?? "You do not have access to that."
        case 423:
            // The Keycloak login path answers 423 with no code of its own.
            if let seconds = problem?.retryAfter {
                return "Too many attempts. Try again \(relative(seconds))."
            }
            return "This account is locked. Try again later, or reset your password."
        case 429:
            if let seconds = problem?.retryAfter {
                return "Too many attempts. Try again \(relative(seconds))."
            }
            return "Too many attempts. Try again in a few minutes."
        case 502, 503, 504:
            return "The server is not answering right now. Try again in a moment."
        default:
            return unknown(status: status, problem: problem)
        }
    }

    /// Every code these flows can raise, and nothing else — an entry here
    /// is a promise that this app knows what the failure means.
    private static func copy(for code: String, problem: Problem?) -> String? {
        switch code {
        // ── the emailed code ────────────────────────────────────────
        case "invalid_email":
            return "That does not look like an email address."
        case "code_invalid":
            if let left = problem?.attemptsLeft, left > 0 {
                return "That code is not right. \(left) \(left == 1 ? "try" : "tries") left."
            }
            return "That code is not right."
        case "challenge_expired":
            return "That code has expired. Send a new one."
        case "challenge_consumed":
            return "That code has already been used. Send a new one."
        case "too_many_attempts":
            return "Too many wrong codes. Send a new one."
        case "rate_limited":
            if let seconds = problem?.retryAfter {
                return "Too many attempts. Try again \(relative(seconds))."
            }
            return "Too many attempts. Try again in a few minutes."
        case "rate_limiter_unavailable":
            return "Sign-in is briefly unavailable. Try again in a moment."
        case "email_delivery_unavailable":
            return "The code could not be sent. Try again in a moment."
        // ── passwords and second factors ─────────────────────────────
        case "email_not_verified":
            // The sign-in screen puts a "Resend" beside this, so the
            // sentence says what is owed rather than what to do next.
            return "Confirm your email first — check your inbox for the link we sent."
        case "use_password":
            // Reached only during the dual-issuer period, and only for an
            // account that predates it. The sign-in screen moves to the
            // password form on this code, so the sentence explains the
            // move rather than reporting a failure.
            return "This account signs in with a password. Enter it below."
        case "legacy_session":
            return "Switching workspace needs the new sign-in. Sign out and sign in with an emailed code, or switch in the web app."
        case "otp_required":
            return "Enter the code from your authenticator."
        case "otp_invalid":
            return "That code is not right."
        case "otp_unavailable":
            return "Two-factor sign-in is unavailable for this account. Ask an administrator."
        case "mfa_enrolment_required":
            return "This workspace requires a second factor. Set one up in the web app first."
        // ── the session ──────────────────────────────────────────────
        case "auth_refresh_replay":
            return SessionLostReason.securityRevoked.message
        case "session_expired", "session_revoked", "no_refresh_token":
            return SessionLostReason.expired.message
        case "account_disabled":
            return "This account has been disabled."
        case "no_workspace":
            return "This account is not a member of any workspace. Ask someone to invite you."
        case "origin_not_allowed":
            // Only reachable if the app stopped identifying itself.
            return "This server refused the request. Check the server address in Settings."
        // ── step-up ─────────────────────────────────────────────────
        case "reauth_required":
            return "Confirm it is really you to continue."
        case "challenge_required":
            return "Ask for a new code before entering one."
        default:
            return nil
        }
    }

    private static func unknown(status: Int, problem: Problem?) -> String {
        var message = problem?.detail ?? problem?.title ?? "Something went wrong (HTTP \(status))."
        if let code = problem?.code, !code.isEmpty {
            message += " [\(code)]"
        }
        if let requestId = problem?.requestId, !requestId.isEmpty {
            message += "\nRequest id: \(requestId)"
        }
        return message
    }

    /// "in 45 seconds" / "in 3 minutes" — a countdown the person can act on.
    static func relative(_ seconds: Int) -> String {
        if seconds <= 1 { return "now" }
        if seconds < 90 { return "in \(seconds) seconds" }
        let minutes = Int((Double(seconds) / 60).rounded())
        return "in \(minutes) minutes"
    }
}
