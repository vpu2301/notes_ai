import XCTest
@testable import NotesAICapture

/// Every auth failure says something a person can act on; unplanned ones say where to look.
final class AuthCopyTests: XCTestCase {
    /// The codes `docs/api/error-codes.md` lists for the endpoints this app
    /// calls while signing in, refreshing or stepping up.
    private let handled = [
        "invalid_email", "code_invalid", "challenge_expired", "challenge_consumed",
        "too_many_attempts", "rate_limited", "rate_limiter_unavailable",
        "email_delivery_unavailable", "otp_required", "otp_invalid", "otp_unavailable",
        "mfa_enrolment_required", "auth_refresh_replay", "session_expired",
        "session_revoked", "no_refresh_token", "account_disabled", "no_workspace",
        "origin_not_allowed", "reauth_required", "challenge_required",
        // The email-code path's 409 for an address that has a password.
        "use_password",
        // A workspace that stopped being reachable.
        "not_a_member", "membership_suspended", "tenant_dissolved",
        // The account exists, before its address is confirmed.
        "email_not_verified",
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

    /// The sentence beside the "Resend" button; a 403 must not fall through to the server's `detail`.
    func testAnUnconfirmedAddressSaysToConfirmIt() {
        let message = AuthCopy.message(for: error("email_not_verified", status: 403))
        XCTAssertEqual(message, "Confirm your email first — we sent you a code.")
    }

    /// A role denial is a bare 403 whose `detail` is about the permission matrix; by now `APIClient` has refreshed and retried, so the sentence must be about the person's situation.
    func testARoleDenialDoesNotQuoteThePermissionMatrix() {
        var problem = Problem(title: "Forbidden",
                              detail: "deny: roles=['viewer'] cannot 'note.write' on 'note'",
                              status: 403, code: nil)
        problem.requestId = "req-1"
        let message = AuthCopy.message(for: APIError.http(status: 403, problem: problem))
        XCTAssertFalse(message.contains("deny:"), "the matrix is not the person's problem")
        XCTAssertTrue(message.contains("not allowed to do that in this workspace"))
    }

    /// A 403 that is NOT a role denial gets a fixed sentence; `detail` may change under the screen.
    func testAnOtherForbiddenSaysSoWithoutTheServersWording() {
        let problem = Problem(title: "Forbidden", detail: "this note is private",
                              status: 403, code: nil)
        let message = AuthCopy.message(for: APIError.http(status: 403, problem: problem))
        XCTAssertEqual(message, "You do not have access to that.")
        XCTAssertFalse(message.contains("this note is private"))
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

    func testAnUnknownCodeCarriesAReferenceAndNothingFromTheServer() {
        let message = AuthCopy.message(for: error("something_new", status: 500,
                                                  detail: "unexpected", requestId: "req-9"))
        XCTAssertTrue(message.contains("req-9"), message)
        XCTAssertFalse(message.contains("unexpected"), "the server's detail is for logs, not people")
        XCTAssertFalse(message.contains("something_new"), "a machine code is not a sentence")
        XCTAssertFalse(message.contains("Request id"), message)
    }

    func testAGenerationRefusalReadsAsASentence() {
        let message = AuthCopy.message(for: error("processor_unacknowledged", status: 409,
                                                  detail: "a workspace admin has to agree", requestId: "req-1"))
        XCTAssertEqual(message, GenerationCopy.processorUnacknowledged)
        XCTAssertTrue(message.hasSuffix("Settings › Data & AI."))
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
}
