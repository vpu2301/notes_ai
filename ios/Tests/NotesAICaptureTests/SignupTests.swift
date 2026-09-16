import XCTest
@testable import NotesAICapture

/// IOS-0 — what this app owes an account that was created on the web.
///
/// Signup itself is not here and is not meant to be: a BE-0 account is an
/// ordinary password account by the time it reaches the phone, and the two
/// things the phone has to know are where to send somebody who has no
/// account (the web app) and what to do with the one answer `/auth/login`
/// gives an account that has not confirmed its address yet.
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
        // Both are 403s from the same endpoint, and they want opposite
        // things from the person: one is a link in their inbox, the other
        // is an administrator. Offering "resend" for a disabled account
        // would send them round a loop that cannot end.
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
        // Asserted on the URL rather than on `UIApplication.open`, which a
        // unit test cannot observe: what matters is that the path is built
        // off the configured web app and not off the auth host, because on
        // a phone those are different machines.
        let settings = BackendSettings.default
        let url = URL(string: settings.webAppURL)?.appending(path: "signup")
        XCTAssertEqual(url?.absoluteString, "http://localhost:5173/signup")

        let onALan = BackendSettings.forHost("192.168.1.20")
        XCTAssertEqual(URL(string: onALan?.webAppURL ?? "")?.appending(path: "signup").absoluteString,
                       "http://192.168.1.20:5173/signup")
    }
}
