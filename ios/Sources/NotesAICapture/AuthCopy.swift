import Foundation

/// What a failed auth request says to the person. One map keyed on the
/// server's `code` (docs/api/error-codes.md); `detail` may change. Unknown
/// codes get a generic line with the request id.
enum AuthCopy {
    // ── sentences the app says without a failed request ──────────────

    /// A link to a note in a workspace this identity is not in.
    static let notAMember = "This note is in a workspace you are not a member of."
    /// A note the open workspace does not have (404 on a link without `?ws=`).
    static let notInThisWorkspace = "Not in this workspace. It may be in another of your workspaces."
    /// A note-level refusal (`insufficient_role`); the action is hidden, so this is rare.
    static let insufficientRole = "Your access to this note does not allow that. Ask its author for more."
    /// The old add-by-e-mail path (`use_invitations`).
    static let useInvitations = "People are added by invitation now. Send them one instead."

    /// The session was moved by the server (left, removed, dissolved) and the app followed it.
    static func workspaceMoved(_ name: String) -> String { "Switched to \(name)." }

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
            // The role gate's `deny: roles=[…] …`; `APIClient` already refreshed once, so this is a real refusal.
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

    /// Every code these flows can raise, and nothing else.
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
            // A "Resend" sits beside this, so the sentence says what is owed.
            return "Confirm your email first — check your inbox for the link we sent."
        case "use_password":
            // The sign-in screen moves to the password form on this code.
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
        // ── invitations and membership (W2) ─────────────────────────
        case "personal_workspace":
            return "Personal is just for you. Create a workspace to invite people."
        case "already_member":
            return "That person is already in this workspace."
        case "use_invitations":
            return useInvitations
        case "invalid_role":
            return "Invitations can make someone a member, an admin or a viewer."
        case "invite_unavailable":
            return "Invitations cannot be sent right now. Try again in a moment."
        case "not_pending":
            return "That invitation is no longer pending."
        case "invitation_not_found":
            return "This invitation is no longer valid. Ask the person who invited you for a new one."
        case "invitation_email_mismatch":
            return "This invitation was sent to a different address."
        case "last_owner":
            return "You are the last owner. Make someone else an owner before you leave."
        case "has_other_members":
            return "Remove everyone else from the workspace first, then dissolve it."
        case "confirm_name_mismatch":
            return "The name does not match. Type the workspace name exactly."
        case "owner_only":
            return "Only an owner can do that."
        // ── switching and borrowed tokens (W1) ──────────────────────
        case "not_a_member":
            return "You are not a member of that workspace any more."
        case "membership_suspended":
            return "Your membership in that workspace is suspended. Ask whoever runs it."
        case "tenant_dissolved":
            return "That workspace has been dissolved."
        // ── the note by level (W3) ──────────────────────────────────
        case "insufficient_role":
            return insufficientRole
        case "is_author":
            return "The note's author always has full access."
        case "origin_not_allowed":
            // Only reachable if the app stopped identifying itself.
            return "This server refused the request. Check the server address in Settings."
        // ── step-up ─────────────────────────────────────────────────
        case "reauth_required":
            return "Confirm it is really you to continue."
        case "challenge_required":
            return "Ask for a new code before entering one."
        // ── writing the note ─────────────────────────────────────────
        // Same sentences as `GenerationView.failureText`.
        case "processor_unacknowledged":
            return GenerationCopy.processorUnacknowledged
        case "generation_disabled":
            return GenerationCopy.generationDisabled
        case "budget_exceeded":
            return GenerationCopy.budgetExceeded
        case "generation_in_progress":
            return "This note is already being written. Give it a moment."
        case "too_many_generations":
            return "This note has been rewritten as often as it can be today. Try again tomorrow."
        case "no_transcript":
            return "This note was not made from a recording, so there is nothing to write it from."
        case "note_cancelled":
            return "This note was cancelled and cannot be written again."
        case "no_snapshot", "snapshot_unreadable":
            return GenerationCopy.recordingUnreadable
        case "model_unavailable":
            return GenerationCopy.modelUnavailable
        case "model_not_configured":
            return "Asking about a note is not set up on this server."
        case "object_store_not_configured":
            return "Recordings cannot be read on this server right now. Try again later."
        default:
            return nil
        }
    }

    /// A failure with no sentence: a generic line plus the first eight characters of the request id.
    private static func unknown(status: Int, problem: Problem?) -> String {
        let base: String
        switch status {
        case 400...499: base = "That could not be done. Try again in a moment."
        case 500...599: base = "The server had a problem. Try again in a moment."
        default: base = "Something went wrong. Try again in a moment."
        }
        return withRef(base, problem: problem)
    }

    /// `message` with the correlation reference appended.
    static func withRef(_ message: String, problem: Problem?) -> String {
        guard let requestId = problem?.requestId, !requestId.isEmpty else { return message }
        return "\(message) (ref \(requestId.prefix(8)))"
    }

    /// The code behind an error, when the server sent one.
    static func code(of error: Error) -> String? {
        guard case APIError.http(_, let problem) = error else { return nil }
        return problem?.code
    }

    /// "in 45 seconds" / "in 3 minutes" — a countdown the person can act on.
    static func relative(_ seconds: Int) -> String {
        if seconds <= 1 { return "now" }
        if seconds < 90 { return "in \(seconds) seconds" }
        let minutes = Int((Double(seconds) / 60).rounded())
        return "in \(minutes) minutes"
    }
}

/// The sentences for a note that was not written (refused start and failed run alike).
enum GenerationCopy {
    static let processorUnacknowledged =
        "A workspace admin has to agree to who processes your meetings before notes are written. Settings › Data & AI."
    static let generationDisabled = "Automatic note writing is off for this workspace."
    static let budgetExceeded =
        "This workspace has used its AI budget for the month, so this note was not written up. Your recording and your own notes are untouched."
    static let recordingUnreadable = "The recording could not be read when the note was written."
    static let modelUnavailable = "The model was unavailable. Try writing the note again."
    static let generic = "This note could not be written automatically."
}
