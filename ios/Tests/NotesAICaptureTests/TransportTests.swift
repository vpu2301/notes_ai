import XCTest
@testable import NotesAICapture

/// IDX-I1 — what leaves this phone on every request, and what does not.
final class TransportTests: XCTestCase {

    func testEveryRequestDeclaresItselfAsThisApp() async {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (200, Fixtures.json(["spaces": []]), [:])
        }

        _ = try? await client.fetchSpaces()

        for request in StubServer.requests {
            // Without this header the server puts the refresh token in a
            // cookie and the origin check treats the app as a browser.
            XCTAssertEqual(request.headers["X-Client-Type"], "ios", "\(request.path)")
            XCTAssertNotNil(UUID(uuidString: request.headers["X-Request-Id"] ?? ""),
                            "\(request.path) carried no request id")
        }
        XCTAssertFalse(StubServer.requests.isEmpty)
    }

    func testNoCookieIsEverSentToTheAuthHost() async {
        // A cookie planted in the shared jar, of the kind the app used to
        // rely on. The session must not carry it.
        let jar = HTTPCookieStorage.shared
        let cookie = HTTPCookie(properties: [
            .domain: "localhost", .path: "/", .name: "planted", .value: "v",
        ])!
        jar.setCookie(cookie)
        defer { jar.deleteCookie(cookie) }

        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
        StubServer.install { _ in (200, Fixtures.authenticated(), [:]) }

        _ = await client.restoreSession()

        let refresh = StubServer.requests(to: "/auth/refresh").first
        XCTAssertNotNil(refresh)
        XCTAssertNil(refresh?.headers["Cookie"])
    }

    func testTheLegacyRefreshCookieIsRemoved() {
        let jar = HTTPCookieStorage.shared
        let stale = HTTPCookie(properties: [
            .domain: "localhost", .path: "/auth", .name: LegacyCookies.name, .value: "old",
        ])!
        let unrelated = HTTPCookie(properties: [
            .domain: "localhost", .path: "/", .name: "keep-me", .value: "v",
        ])!
        jar.setCookie(stale)
        jar.setCookie(unrelated)
        defer { jar.deleteCookie(unrelated) }

        let removed = LegacyCookies.purge(from: jar)

        XCTAssertGreaterThanOrEqual(removed, 1)
        XCTAssertFalse((jar.cookies ?? []).contains { $0.name == LegacyCookies.name })
        XCTAssertTrue((jar.cookies ?? []).contains { $0.name == "keep-me" },
                      "only the app's own stale credential is removed")
    }

    func testTheAccessTokenIsSentAsABearerAndNeverStored() async {
        let storage = InMemorySessionStorage(seed: Fixtures.record())
        let client = makeClient(storage: storage)
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(accessToken: "at-42"), [:])
                : (200, Fixtures.json(["spaces": []]), [:])
        }

        _ = try? await client.fetchSpaces()

        let spaces = StubServer.requests(to: "/v1/spaces").first
        XCTAssertEqual(spaces?.headers["Authorization"], "Bearer at-42")
        let stored = String(data: storage.read() ?? Data(), encoding: .utf8) ?? ""
        XCTAssertFalse(stored.contains("at-42"), "the access token is memory-only")
    }

    func testARequestIdComesBackOnAFailureNobodyRecognises() async {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (500, Fixtures.json(["detail": "boom", "code": "kaboom"]),
                   ["X-Request-Id": "req-7"])
        }

        do {
            _ = try await client.fetchSpaces()
            XCTFail("expected the 500 to surface")
        } catch let error as APIError {
            XCTAssertEqual(error.problem?.requestId, "req-7")
            let message = AuthCopy.message(for: error)
            XCTAssertTrue(message.contains("req-7"), message)
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testRetryAfterIsReadFromTheHeader() async {
        let client = makeClient(storage: InMemorySessionStorage())
        StubServer.install { _ in
            (429, Fixtures.json(["code": "rate_limited", "detail": "slow down"]),
             ["Retry-After": "45"])
        }

        do {
            _ = try await client.startEmailCode(email: "olena@acme.example")
            XCTFail("expected the 429")
        } catch let error as APIError {
            XCTAssertEqual(error.problem?.retryAfter, 45)
            XCTAssertEqual(AuthCopy.message(for: error), "Too many attempts. Try again in 45 seconds.")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testAStepUpIsAnsweredOnceAndTheRequestRetried() async {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
        let asked = Counter()
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/v1/spaces":
                return asked.next() == 1
                    ? (403, Fixtures.json(["code": "reauth_required", "detail": "prove it"]), [:])
                    : (200, Fixtures.json(["spaces": []]), [:])
            default:
                return (404, Data(), [:])
            }
        }
        let prompts = Counter()
        await client.onReauthRequired {
            _ = prompts.next()
            return true
        }

        let spaces = try? await client.fetchSpaces()

        XCTAssertNotNil(spaces)
        XCTAssertEqual(prompts.next() - 1, 1, "asked exactly once")
    }

    func testAStepUpTheUserCancelsSurfacesAsReauthRequired() async {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (403, Fixtures.json(["code": "reauth_required"]), [:])
        }
        await client.onReauthRequired { false }

        do {
            _ = try await client.fetchSpaces()
            XCTFail("expected the step-up to stand")
        } catch APIError.reauthRequired {
            // The caller decides what to say; the client does not retry.
        } catch {
            XCTFail("unexpected \(error)")
        }
    }
}
