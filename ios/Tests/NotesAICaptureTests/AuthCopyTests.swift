import XCTest
@testable import NotesAICapture

/// Every auth failure says something a person can act on; unknown ones say where to look.
final class AuthCopyTests: XCTestCase {
    /// The codes `docs/api/error-codes.md` lists for sign-in, refresh and step-up.
    private let handled = [
        "invalid_email", "code_invalid", "challenge_expired", "challenge_consumed",
        "too_many_attempts", "rate_limited", "rate_limiter_unavailable",
        "email_delivery_unavailable", "otp_required", "otp_invalid", "otp_unavailable",
        "mfa_enrolment_required", "auth_refresh_replay", "session_expired",
        "session_revoked", "no_refresh_token", "account_disabled", "no_workspace",
        "origin_not_allowed", "reauth_required", "challenge_required",
        // The two the dual-issuer period adds (ADR-0047), and the signup one.
        "use_password", "legacy_session", "email_not_verified",
    ]

    private func error(_ code: String, status: Int = 400,
                       detail: String = "server wording", requestId: String? = nil,
                       attemptsLeft: Int? = nil) -> APIError {
        var problem = Problem(title: nil, detail: detail, status: status, code: code)
        problem.requestId = requestId
        problem.attemptsLeft = attemptsLeft
        return .http(status: status, problem: problem)
    }

    func testEveryHandledCodeHasItsOwnSentence() {
        var seen: Set<String> = []
        for code in handled {
            let message = AuthCopy.message(for: error(code))
            XCTAssertFalse(message.contains("server wording"),
                           "\(code) fell through to the server's `detail`")
            XCTAssertFalse(message.contains(code), "\(code) leaked its machine code")
            XCTAssertFalse(message.isEmpty)
            seen.insert(message)
        }
        XCTAssertGreaterThan(seen.count, 10, "the map should not answer everything the same way")
    }

    func testAWrongCodeSaysHowManyTriesAreLeft() {
        let message = AuthCopy.message(for: error("code_invalid", attemptsLeft: 3))
        XCTAssertEqual(message, "That code is not right. 3 tries left.")
        XCTAssertEqual(AuthCopy.message(for: error("code_invalid", attemptsLeft: 1)),
                       "That code is not right. 1 try left.")
    }

    func testAReplayReadsAsSecurityNotAsAnExpiry() {
        XCTAssertEqual(AuthCopy.message(for: error("auth_refresh_replay", status: 401)),
                       SessionLostReason.securityRevoked.message)
        XCTAssertNotEqual(AuthCopy.message(for: error("session_expired", status: 401)),
                          SessionLostReason.securityRevoked.message)
    }

    /// An unknown failure is one generic sentence plus a short reference, never the server's wording.
    func testAnUnknownCodeCarriesTheRequestId() {
        let message = AuthCopy.message(for: error("something_new", status: 500,
                                                  detail: "unexpected", requestId: "req-9"))
        XCTAssertFalse(message.contains("unexpected"))
        XCTAssertFalse(message.contains("something_new"))
        XCTAssertTrue(message.contains("req-9"))
        XCTAssertTrue(message.hasPrefix("The server had a problem."), message)
    }

    /// The codes the note engine answers with are written out, and the
    /// processor one says where to go.
    func testGenerationCodesAreWrittenOut() {
        let message = AuthCopy.message(for: error("processor_unacknowledged", status: 409,
                                                  detail: "a workspace admin has to agree"))
        XCTAssertFalse(message.contains("a workspace admin has to agree"))
        XCTAssertTrue(message.contains("Settings › Data & AI"))
        XCTAssertEqual(AuthCopy.message(for: error("generation_disabled", status: 409)),
                       GenerationCopy.generationDisabled)
        XCTAssertEqual(AuthCopy.code(of: error("budget_exceeded", status: 409)), "budget_exceeded")
    }

    func testALockedAccountCountsDown() {
        var problem = Problem(title: nil, detail: "locked", status: 423, code: nil)
        problem.retryAfter = 300
        XCTAssertEqual(AuthCopy.message(for: APIError.http(status: 423, problem: problem)),
                       "Too many attempts. Try again in 5 minutes.")
    }

    func testTheClientsOwnErrorsSpeakForThemselves() {
        XCTAssertEqual(AuthCopy.message(for: APIError.sessionRevoked),
                       SessionLostReason.securityRevoked.message)
        XCTAssertTrue(AuthCopy.message(for: APIError.badURL).contains("Settings"))
    }

    // MARK: - Completeness against docs/api/error-codes.md (IOS-12)

    /// Codes the doc lists that this app never meets: the endpoint is the web app's, a device's,
    /// or retired. A new code in the doc fails the test until it gets copy or a line here.
    private let notReachableFromThisApp: [String: String] = [
        "signup_rate_limited": "signup is a web flow (`openSignup`)",
        "password_policy": "signup is a web flow",
        "display_name_required": "signup is a web flow",
        "signup_unavailable": "signup is a web flow",
        "verify_retry": "signup is a web flow",
        "mfa_already_enabled": "second factors are managed on the web",
        "mfa_not_enabled": "second factors are managed on the web",
        "owner_reset_requires_owner": "second factors are managed on the web",
        "email_in_use": "changing the address is on the web",
        "email_unchanged": "changing the address is on the web",
        "sole_owner_with_members": "account deletion is on the web",
        "confirm_required": "account deletion is on the web",
        "invalid_client": "OAuth client credentials (devices), not people",
        "unsupported_grant_type": "OAuth client credentials (devices)",
        "client_rate_limited": "OAuth client credentials (devices)",
        "client_locked": "OAuth client credentials (devices)",
        "try_again": "OAuth client credentials (devices)",
        "rotation_in_progress": "device credential rotation",
        "speakers_hint_invalid": "retired in Sprint 30",
        "name_candidates_invalid": "a field this app builds within the limits; a refusal is a client bug",
        "channel_layout_mismatch": "sent by the macOS app only",
        "local_speaker_name_invalid": "sent by the macOS app only",
    ]

    /// Every `code` in the table's first column.
    private func documentedCodes() throws -> Set<String> {
        let doc = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent()
            .appending(path: "docs/api/error-codes.md")
        let text = try String(contentsOf: doc, encoding: .utf8)
        var codes: Set<String> = []
        for line in text.split(separator: "\n") where line.hasPrefix("| `") {
            let rest = line.dropFirst(3)
            guard let end = rest.firstIndex(of: "`") else { continue }
            let code = String(rest[..<end])
            if code.range(of: "^[a-z_]+$", options: .regularExpression) != nil { codes.insert(code) }
        }
        return codes
    }

    /// Copy of its own: not the generic line an unknown code gets, never the server's wording,
    /// or a typed error the speaker screens explain.
    private func hasCopy(_ code: String) -> Bool {
        let failure = error(code, status: 418)
        if SpeakerEditError.from(failure) is SpeakerEditError { return true }
        if RediarizeError.from(failure) is RediarizeError { return true }
        let message = AuthCopy.message(for: failure)
        let generic = AuthCopy.message(for: error("zz_not_a_code", status: 418))
        return message != generic && !message.contains("server wording") && !message.contains(code)
    }

    func testEveryDocumentedCodeHasCopyOrAReasonItCannotHappen() throws {
        let codes = try documentedCodes()
        XCTAssertGreaterThan(codes.count, 60, "the doc was not parsed")
        let missing = codes.filter { !hasCopy($0) && notReachableFromThisApp[$0] == nil }.sorted()
        XCTAssertEqual(missing, [], "codes in docs/api/error-codes.md without copy")
        // An exemption for a code that has copy (or left the doc) is stale.
        let stale = notReachableFromThisApp.keys.filter { hasCopy($0) || !codes.contains($0) }.sorted()
        XCTAssertEqual(stale, [], "exemptions that no longer apply")
    }

    /// The workspace and collaboration codes (W1–W3) by name, so a doc edit cannot drop one silently.
    func testWorkspaceAndCollaborationCodesHaveCopy() {
        for code in ["already_member", "invite_unavailable", "not_pending", "invitation_not_found",
                     "invitation_email_mismatch", "last_owner", "owner_only", "has_other_members",
                     "confirm_name_mismatch", "insufficient_role", "is_author", "use_invitations",
                     "personal_workspace", "invalid_role", "not_a_member", "membership_suspended",
                     "tenant_dissolved"] {
            XCTAssertTrue(hasCopy(code), code)
        }
        XCTAssertEqual(AuthCopy.message(for: error("insufficient_role", status: 403)), AuthCopy.insufficientRole)
        XCTAssertEqual(AuthCopy.message(for: error("use_invitations", status: 410)), AuthCopy.useInvitations)
    }
}
