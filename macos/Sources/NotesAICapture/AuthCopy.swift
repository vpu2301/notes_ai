import Foundation

/// What a failed auth request says to the person.
///
/// One map keyed on the server's `code` (`docs/api/error-codes.md`); `detail` may
/// change and never reaches the screen. Anything unrecognised falls through to a
/// generic line with a short reference from the request id.
enum AuthCopy {
    static func message(for error: Error) -> String {
        guard let apiError = error as? APIError else { return error.localizedDescription }
        switch apiError {
        case .badURL, .notAuthenticated, .sessionRevoked, .reauthRequired,
             .malformedResponse, .noNativeSession:
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
            // A role denial (`deny: roles=[…] cannot …`) carries no code. `APIClient`
            // has already refreshed once, so this is a real refusal: name who can change it.
            if let detail = problem?.detail, detail.hasPrefix("deny:") {
                return "This account is not allowed to do that in this workspace. Ask whoever runs it to give you access."
            }
            return "You do not have access to that."
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
        case "use_password":
            // 409 on the email-code path: the address has a password; the screen moves to the password step.
            return "This account signs in with a password."
        case "otp_required":
            return "Enter the code from your authenticator."
        case "otp_invalid":
            return "That code is not right."
        case "otp_unavailable":
            return "Two-factor sign-in is unavailable for this account. Ask an administrator."
        case "mfa_enrolment_required":
            return "This workspace requires a second factor. Set one up in the web app first."
        // ── signup ───────────────────────────────────────────────────
        case "email_not_verified":
            // 403 on `/auth/login`: right password, unconfirmed address. The screen also offers "Resend".
            return "Confirm your email first — we sent you a code."
        // ── the session ──────────────────────────────────────────────
        case "auth_refresh_replay":
            return SessionLostReason.securityRevoked.message
        case "session_expired", "session_revoked", "no_refresh_token":
            return SessionLostReason.expired.message
        case "account_disabled":
            return "This account has been disabled."
        // ── workspaces ──────────────────────────────────────────────
        case "not_a_member":
            return "You are no longer a member of that workspace."
        case "membership_suspended":
            return "Your membership is suspended."
        case "tenant_dissolved":
            return "That workspace has been closed."
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
        // ── writing a note ──────────────────────────────────────────
        // The same sentences the status line uses, so a refusal and a failure read as one thing.
        case "processor_unacknowledged":
            return GenerationCopy.processorUnacknowledged
        case "generation_disabled":
            return GenerationCopy.generationDisabled
        case "budget_exceeded":
            return GenerationCopy.budgetExceeded
        case "generation_in_progress":
            return GenerationCopy.inProgress
        case "too_many_generations":
            return GenerationCopy.tooMany
        case "no_transcript":
            return GenerationCopy.noTranscript
        case "note_cancelled":
            return GenerationCopy.cancelled
        case "model_unavailable":
            return GenerationCopy.modelUnavailable
        case "no_snapshot", "snapshot_unreadable":
            return GenerationCopy.recordingUnreadable
        case "no_client_version":
            return "This kind of note has no client version — nothing in it is meant for someone outside the workspace."
        default:
            return nil
        }
    }

    /// The one sentence for a failure this app cannot explain, plus a reference the person can quote.
    private static func unknown(status: Int, problem: Problem?) -> String {
        let base: String
        switch status {
        case 400..<500: base = "That request could not be completed."
        case 500..<600: base = "The server ran into a problem."
        default: base = "Something went wrong."
        }
        guard let ref = reference(problem?.requestId) else { return "\(base) Try again." }
        return "\(base) Try again, or quote reference \(ref)."
    }

    /// The first eight characters of the request id: enough to find it in the logs.
    static func reference(_ requestId: String?) -> String? {
        guard let requestId = requestId?.trimmingCharacters(in: .whitespaces), !requestId.isEmpty else { return nil }
        return String(requestId.prefix(8))
    }

    /// "in 45 seconds" / "in 3 minutes" — a countdown the person can act on.
    static func relative(_ seconds: Int) -> String {
        if seconds <= 1 { return "now" }
        if seconds < 90 { return "in \(seconds) seconds" }
        let minutes = Int((Double(seconds) / 60).rounded())
        return "in \(minutes) minutes"
    }
}
