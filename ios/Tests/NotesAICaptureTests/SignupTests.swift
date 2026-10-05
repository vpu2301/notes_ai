import XCTest
@testable import NotesAICapture

/// What this app owes an account created on the web: where to send someone
/// with no account, and what to do with `403 email_not_verified`.
final class SignupTests: XCTestCase {

    // MARK: - `403 email_not_verified`

    private func problem(_ code: String, status: Int, detail: String = "no") -> Data {
        Fixtures.json(["title": "Forbidden", "status": status, "detail": detail, "code": code])
    }

    func testAnUnconfirmedAccountIsToldToReadItsMail() async {
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { _ in (403, self.problem("email_not_verified", status: 403), [:]) }

        do {
            _ = try await client.login(email: "new@acme.example", password: "hunter2")
            XCTFail("an unconfirmed account cannot sign in")
        } catch let error as APIError {
            XCTAssertTrue(error.isEmailNotVerified)
            XCTAssertEqual(AuthCopy.message(for: error),
                           "Confirm your email first — check your inbox for the link we sent.")
        } catch {
            XCTFail("unexpected \(error)")
        }
        XCTAssertNil(storage.record, "nothing is stored for a sign-in that did not happen")
    }

    func testADisabledAccountIsNotMistakenForAnUnconfirmedOne() async {
        // Both are 403s; "resend" for a disabled account would be a loop that cannot end.
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { _ in (403, self.problem("account_disabled", status: 403), [:]) }

        do {
            _ = try await client.login(email: "gone@acme.example", password: "hunter2")
            XCTFail("a disabled account cannot sign in")
        } catch let error as APIError {
            XCTAssertFalse(error.isEmailNotVerified)
            XCTAssertEqual(AuthCopy.message(for: error), "This account has been disabled.")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testAWrongPasswordIsNotAnUnconfirmedAddress() async {
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { _ in (401, Fixtures.problem("invalid_credentials"), [:]) }

        do {
            _ = try await client.login(email: "someone@acme.example", password: "wrong")
            XCTFail("the server refused")
        } catch let error as APIError {
            XCTAssertFalse(error.isEmailNotVerified)
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    // MARK: - `POST /auth/signup/resend`

    func testResendAsksTheServerAndSaysNothingAboutTheAddress() async throws {
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { _ in (202, Data(), [:]) }

        try await client.resendVerification(email: "new@acme.example")

        let sent = StubServer.requests(to: "/auth/signup/resend").first
        XCTAssertEqual(sent?.method, "POST")
        XCTAssertEqual(sent?.json()["email"] as? String, "new@acme.example")
        XCTAssertNil(sent?.headers["Authorization"],
                     "the caller cannot sign in — that is the whole problem")
        XCTAssertEqual(sent?.headers["X-Client-Type"], "ios")
    }

    func testResendSurfacesARateLimitRatherThanClaimingSuccess() async {
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { _ in
            (429, Fixtures.json(["status": 429, "code": "rate_limited"]), ["Retry-After": "120"])
        }

        do {
            try await client.resendVerification(email: "new@acme.example")
            XCTFail("the server refused")
        } catch let error as APIError {
            XCTAssertEqual(AuthCopy.message(for: error), "Too many attempts. Try again in 2 minutes.")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    // MARK: - Where "Create one" goes

    @MainActor
    func testSignupOpensTheWebApp() {
        // Asserted on the URL: it must be built off the web app, not the auth host.
        let settings = BackendSettings.default
        let url = URL(string: settings.webAppURL)?.appending(path: "signup")
        XCTAssertEqual(url?.absoluteString, "http://localhost:5173/signup")

        let onALan = BackendSettings.forHost("192.168.1.20")
        XCTAssertEqual(URL(string: onALan?.webAppURL ?? "")?.appending(path: "signup").absoluteString,
                       "http://192.168.1.20:5173/signup")
    }
}
