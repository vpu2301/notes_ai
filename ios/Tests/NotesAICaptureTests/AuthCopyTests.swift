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
}
