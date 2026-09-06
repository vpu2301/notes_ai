import XCTest
@testable import NotesAICapture

/// MAC-0 — the two pieces of signup this app owns: the link out to the
/// web app's form, and the one button that rescues an account whose
/// address was never confirmed.
final class SignupTests: XCTestCase {

    // MARK: - The link out

    func testSignupURLIsTheWebAppsSignupPage() {
        var settings = BackendSettings.default
        settings.webAppURL = "https://app.example.com"
        XCTAssertEqual(url(for: settings)?.absoluteString, "https://app.example.com/signup")
    }

    /// Settings are typed by hand, and a pasted address usually arrives
    /// with a space or a trailing slash on it. Neither may produce a URL
    /// that 404s in the browser.
    func testSignupURLToleratesAHandTypedServerAddress() {
        var settings = BackendSettings.default
        settings.webAppURL = "  https://app.example.com/  "
        XCTAssertEqual(url(for: settings)?.absoluteString, "https://app.example.com/signup")
    }

    private func url(for settings: BackendSettings) -> URL? {
        URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: "signup")
    }

    // MARK: - Resending the confirmation

    func testResendPostsTheAddressUnauthenticated() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
        StubServer.install { _ in (202, Data("{}".utf8), [:]) }

        try await client.resendSignupVerification(email: "olena@acme.example")

        let sent = try XCTUnwrap(StubServer.requests(to: "/auth/signup/resend").first)
        XCTAssertEqual(sent.method, "POST")
        XCTAssertEqual(sent.json()["email"] as? String, "olena@acme.example")
        // Nobody is signed in yet by definition — a token here would be a
        // stale one from a previous account on this Mac.
        XCTAssertNil(sent.headers["Authorization"])
    }

    /// The endpoint is rate limited (it sends mail). The screen has to be
    /// able to say why, so the error must survive as an `APIError` with
    /// its code rather than being swallowed.
    func testResendSurfacesTheRateLimit() async {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
        StubServer.install { _ in
            // The wait comes from `Retry-After`, the way the app reads it.
            (429, Fixtures.json(["code": "rate_limited", "status": 429]), ["Retry-After": "60"])
        }

        do {
            try await client.resendSignupVerification(email: "olena@acme.example")
            XCTFail("a 429 must not look like success")
        } catch let error as APIError {
            XCTAssertEqual(error.code, "rate_limited")
            XCTAssertEqual(AuthCopy.message(for: error), "Too many attempts. Try again in 60 seconds.")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    /// The failure that makes the button appear in the first place: a
    /// password that was right, on an account that is not confirmed.
    func testLoginRefusesAnUnconfirmedAddressWithACodeTheScreenKnows() async {
        let client = makeClient(storage: InMemorySessionStorage())
        StubServer.install { _ in
            (403, Fixtures.json([
                "code": "email_not_verified", "status": 403,
                "detail": "email not verified",
            ]), [:])
        }

        do {
            _ = try await client.login(email: "olena@acme.example", password: "hunter2")
            XCTFail("an unconfirmed account must not get a session")
        } catch let error as APIError {
            XCTAssertEqual(error.code, "email_not_verified")
            XCTAssertEqual(error.status, 403)
        } catch {
            XCTFail("unexpected \(error)")
        }
    }
}
