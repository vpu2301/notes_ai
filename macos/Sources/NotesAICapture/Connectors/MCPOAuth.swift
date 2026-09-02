import AppKit
import AuthenticationServices
import CryptoKit
import Foundation
import Network

/// The OAuth 2.1 dance remote MCP servers expect from a native client
/// (the MCP authorization spec): discover the authorization server from
/// the resource's metadata, register this app as a client on the fly
/// (RFC 7591), send the user to the browser with PKCE, and swap the code
/// for tokens. The callback comes back on the app's own URL scheme,
/// `notesai://oauth/callback`, which ASWebAuthenticationSession intercepts.
enum MCPOAuth {
    static let redirectScheme = "notesai"
    static let redirectURI = "notesai://oauth/callback"
    /// For servers that do not register clients themselves (HubSpot): the
    /// user creates an app on their side and enters this redirect URL.
    static let loopbackPort: UInt16 = 52581
    static let loopbackRedirectURI = "http://localhost:\(loopbackPort)/callback"

    struct Tokens: Codable, Equatable, Sendable {
        var accessToken: String
        var refreshToken: String?
        var expiresAt: Date?
        var scope: String?

        var isExpired: Bool {
            guard let expiresAt else { return false }
            return expiresAt.timeIntervalSinceNow < 60
        }
    }

    /// What the app keeps per server so refreshes and re-logins work
    /// without rediscovering everything.
    struct Registration: Codable, Equatable, Sendable {
        var authorizationEndpoint: URL
        var tokenEndpoint: URL
        var clientId: String
        var clientSecret: String?
        var scopes: [String]
        /// RFC 8707 resource indicator: the MCP server URL.
        var resource: String
        /// The custom scheme for self-registered clients, loopback for
        /// user-supplied ones.
        var redirectURI: String = MCPOAuth.redirectURI
    }

    enum Failure: Error, LocalizedError {
        case noAuthorizationServer
        case needsClientId
        case registrationRefused(String)
        case cancelled
        case badCallback
        case loopbackBusy
        case tokenExchange(String)

        var errorDescription: String? {
            switch self {
            case .noAuthorizationServer: return "The server does not publish an OAuth authorization server."
            case .needsClientId: return "This server does not register apps itself — enter a client ID (Edit…)."
            case .registrationRefused(let why): return "The server refused to register this app: \(why)"
            case .cancelled: return "Sign-in was cancelled."
            case .badCallback: return "The sign-in page came back without an authorization code."
            case .loopbackBusy: return "Port \(MCPOAuth.loopbackPort) is in use; close the other app and retry."
            case .tokenExchange(let why): return "Could not exchange the code for a token: \(why)"
            }
        }
    }

    // MARK: - Discovery

    /// RFC 9728 protected-resource metadata → RFC 8414 / OIDC server
    /// metadata. Falls back to `<origin>/.well-known/…` when the 401 gave
    /// no hint, which is how older servers behave.
    static func discover(server: URL, resourceMetadataURL: URL?) async throws -> (authorizationServer: URL, metadata: [String: Any]) {
        var origin = URLComponents()
        origin.scheme = server.scheme
        origin.host = server.host()
        origin.port = server.port
        let originURL = origin.url!

        var candidates: [URL] = []
        if let resourceMetadataURL { candidates.append(resourceMetadataURL) }
        let path = server.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if !path.isEmpty {
            candidates.append(originURL.appending(path: ".well-known/oauth-protected-resource/\(path)"))
        }
        candidates.append(originURL.appending(path: ".well-known/oauth-protected-resource"))

        var authorizationServers: [URL] = []
        for url in candidates {
            guard let json = try? await getJSON(url),
                  let servers = json["authorization_servers"] as? [String] else { continue }
            authorizationServers = servers.compactMap(URL.init(string:))
            if !authorizationServers.isEmpty { break }
        }
        // No resource metadata: the MCP server's own origin may be the
        // authorization server.
        if authorizationServers.isEmpty { authorizationServers = [originURL] }

        for authServer in authorizationServers {
            for metadataURL in serverMetadataCandidates(for: authServer) {
                if let json = try? await getJSON(metadataURL),
                   json["authorization_endpoint"] is String, json["token_endpoint"] is String {
                    return (authServer, json)
                }
            }
        }
        throw Failure.noAuthorizationServer
    }

    private static func serverMetadataCandidates(for issuer: URL) -> [URL] {
        var origin = URLComponents()
        origin.scheme = issuer.scheme
        origin.host = issuer.host()
        origin.port = issuer.port
        let originURL = origin.url!
        let path = issuer.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        var urls: [URL] = []
        if !path.isEmpty {
            urls.append(originURL.appending(path: ".well-known/oauth-authorization-server/\(path)"))
            urls.append(originURL.appending(path: ".well-known/openid-configuration/\(path)"))
            urls.append(issuer.appending(path: ".well-known/openid-configuration"))
        }
        urls.append(originURL.appending(path: ".well-known/oauth-authorization-server"))
        urls.append(originURL.appending(path: ".well-known/openid-configuration"))
        return urls
    }

    // MARK: - Dynamic client registration

    /// Register this app with the server, or — when the user brought their
    /// own client id (HubSpot) — use that with the loopback redirect.
    static func register(server: URL, metadata: [String: Any],
                         clientId: String? = nil, clientSecret: String? = nil) async throws -> Registration {
        guard let authorizationEndpoint = (metadata["authorization_endpoint"] as? String).flatMap(URL.init(string:)),
              let tokenEndpoint = (metadata["token_endpoint"] as? String).flatMap(URL.init(string:))
        else { throw Failure.noAuthorizationServer }
        let scopes = metadata["scopes_supported"] as? [String] ?? []
        let resource = server.absoluteString

        if let clientId, !clientId.isEmpty {
            return Registration(authorizationEndpoint: authorizationEndpoint, tokenEndpoint: tokenEndpoint,
                                clientId: clientId, clientSecret: clientSecret,
                                scopes: scopes, resource: resource, redirectURI: loopbackRedirectURI)
        }
        guard let registrationEndpoint = (metadata["registration_endpoint"] as? String).flatMap(URL.init(string:)) else {
            throw Failure.needsClientId
        }
        var request = URLRequest(url: registrationEndpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 20
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "client_name": "Notes AI Capture",
            "client_uri": "https://notes.ai",
            "redirect_uris": [redirectURI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "application_type": "native",
        ] as [String: Any])
        let (data, raw) = try await URLSession.shared.data(for: request)
        guard let response = raw as? HTTPURLResponse, (200..<300).contains(response.statusCode),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let clientId = json["client_id"] as? String
        else {
            let body = String(data: data, encoding: .utf8) ?? ""
            throw Failure.registrationRefused(body.isEmpty ? "HTTP \((raw as? HTTPURLResponse)?.statusCode ?? 0)" : String(body.prefix(200)))
        }
        return Registration(authorizationEndpoint: authorizationEndpoint, tokenEndpoint: tokenEndpoint,
                            clientId: clientId, clientSecret: json["client_secret"] as? String,
                            scopes: scopes, resource: resource)
    }

    // MARK: - Browser sign-in (PKCE)

    @MainActor
    static func authorize(_ registration: Registration) async throws -> Tokens {
        let verifier = randomString(64)
        let challenge = Data(SHA256.hash(data: Data(verifier.utf8))).base64URL
        let state = randomString(24)

        var components = URLComponents(url: registration.authorizationEndpoint, resolvingAgainstBaseURL: false)!
        var items = components.queryItems ?? []
        items += [
            URLQueryItem(name: "response_type", value: "code"),
            URLQueryItem(name: "client_id", value: registration.clientId),
            URLQueryItem(name: "redirect_uri", value: registration.redirectURI),
            URLQueryItem(name: "code_challenge", value: challenge),
            URLQueryItem(name: "code_challenge_method", value: "S256"),
            URLQueryItem(name: "state", value: state),
            URLQueryItem(name: "resource", value: registration.resource),
        ]
        if !registration.scopes.isEmpty {
            items.append(URLQueryItem(name: "scope", value: registration.scopes.joined(separator: " ")))
        }
        components.queryItems = items
        let callback: URL
        if registration.redirectURI == loopbackRedirectURI {
            callback = try await LoopbackCallback.run(open: components.url!)
        } else {
            callback = try await BrowserSession.shared.run(url: components.url!)
        }

        guard let query = URLComponents(url: callback, resolvingAgainstBaseURL: false)?.queryItems else {
            throw Failure.badCallback
        }
        if let error = query.first(where: { $0.name == "error" })?.value {
            let description = query.first(where: { $0.name == "error_description" })?.value ?? error
            throw Failure.tokenExchange(description)
        }
        guard query.first(where: { $0.name == "state" })?.value == state,
              let code = query.first(where: { $0.name == "code" })?.value
        else { throw Failure.badCallback }

        return try await exchange(registration, form: [
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": registration.redirectURI,
            "code_verifier": verifier,
        ])
    }

    static func refresh(_ registration: Registration, refreshToken: String) async throws -> Tokens {
        var tokens = try await exchange(registration, form: [
            "grant_type": "refresh_token",
            "refresh_token": refreshToken,
        ])
        if tokens.refreshToken == nil { tokens.refreshToken = refreshToken }
        return tokens
    }

    private static func exchange(_ registration: Registration, form: [String: String]) async throws -> Tokens {
        var fields = form
        fields["client_id"] = registration.clientId
        fields["resource"] = registration.resource
        if let secret = registration.clientSecret { fields["client_secret"] = secret }

        var request = URLRequest(url: registration.tokenEndpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 20
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = fields
            .map { "\($0.key)=\($0.value.addingPercentEncoding(withAllowedCharacters: .formField) ?? "")" }
            .joined(separator: "&")
            .data(using: .utf8)
        let (data, raw) = try await URLSession.shared.data(for: request)
        guard let response = raw as? HTTPURLResponse,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { throw Failure.tokenExchange("unreadable reply") }
        guard (200..<300).contains(response.statusCode), let access = json["access_token"] as? String else {
            let why = json["error_description"] as? String ?? json["error"] as? String ?? "HTTP \(response.statusCode)"
            throw Failure.tokenExchange(why)
        }
        let expiresIn = (json["expires_in"] as? Double) ?? (json["expires_in"] as? Int).map(Double.init)
        return Tokens(accessToken: access,
                      refreshToken: json["refresh_token"] as? String,
                      expiresAt: expiresIn.map { Date().addingTimeInterval($0) },
                      scope: json["scope"] as? String)
    }

    // MARK: - Helpers

    private static func getJSON(_ url: URL) async throws -> [String: Any]? {
        var request = URLRequest(url: url)
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(MCPClient.protocolVersion, forHTTPHeaderField: "MCP-Protocol-Version")
        let (data, raw) = try await URLSession.shared.data(for: request)
        guard let response = raw as? HTTPURLResponse, (200..<300).contains(response.statusCode) else { return nil }
        return try JSONSerialization.jsonObject(with: data) as? [String: Any]
    }

    private static func randomString(_ length: Int) -> String {
        let alphabet = Array("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        return String((0..<length).map { _ in alphabet.randomElement()! })
    }
}

private extension Data {
    var base64URL: String {
        base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}

private extension CharacterSet {
    static let formField: CharacterSet = {
        var set = CharacterSet.alphanumerics
        set.insert(charactersIn: "-._~")
        return set
    }()
}

/// One ASWebAuthenticationSession at a time, anchored to the main window.
@MainActor
private final class BrowserSession: NSObject, ASWebAuthenticationPresentationContextProviding {
    static let shared = BrowserSession()
    private var current: ASWebAuthenticationSession?

    func run(url: URL) async throws -> URL {
        current?.cancel()
        return try await withCheckedThrowingContinuation { continuation in
            let session = ASWebAuthenticationSession(url: url, callbackURLScheme: MCPOAuth.redirectScheme) { callback, error in
                if let callback {
                    continuation.resume(returning: callback)
                } else if let error = error as? ASWebAuthenticationSessionError, error.code == .canceledLogin {
                    continuation.resume(throwing: MCPOAuth.Failure.cancelled)
                } else {
                    continuation.resume(throwing: error ?? MCPOAuth.Failure.badCallback)
                }
            }
            session.presentationContextProvider = self
            session.prefersEphemeralWebBrowserSession = false
            current = session
            if !session.start() {
                continuation.resume(throwing: MCPOAuth.Failure.badCallback)
            }
        }
    }

    nonisolated func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        MainActor.assumeIsolated {
            NSApp.keyWindow ?? NSApp.windows.first { $0.isVisible } ?? NSWindow()
        }
    }
}

/// A one-shot HTTP listener on localhost for the OAuth redirect, for
/// servers whose app settings only accept https or localhost redirect
/// URLs. Opens the sign-in page in the default browser, answers the one
/// GET with a "you can close this tab" page, and hands back the URL.
private enum LoopbackCallback {
    @MainActor
    static func run(open url: URL) async throws -> URL {
        let listener: NWListener
        do {
            listener = try NWListener(using: .tcp, on: NWEndpoint.Port(rawValue: MCPOAuth.loopbackPort)!)
        } catch {
            throw MCPOAuth.Failure.loopbackBusy
        }
        let queue = DispatchQueue(label: "ai.notes.capture.oauth-loopback")
        return try await withCheckedThrowingContinuation { continuation in
            let done = Resumer(continuation)
            listener.stateUpdateHandler = { state in
                switch state {
                case .ready: NSWorkspace.shared.open(url)
                case .failed: done.resume(.failure(MCPOAuth.Failure.loopbackBusy)); listener.cancel()
                case .cancelled: done.resume(.failure(MCPOAuth.Failure.cancelled))
                default: break
                }
            }
            listener.newConnectionHandler = { connection in
                connection.start(queue: queue)
                connection.receive(minimumIncompleteLength: 1, maximumLength: 16384) { data, _, _, _ in
                    let request = data.flatMap { String(data: $0, encoding: .utf8) } ?? ""
                    let target = request.split(separator: " ", maxSplits: 2).dropFirst().first.map(String.init) ?? "/"
                    let callback = URL(string: "http://localhost:\(MCPOAuth.loopbackPort)\(target)")
                    let html = "<!doctype html><meta charset=utf-8><title>Notes AI Capture</title><body style=\"font-family:-apple-system,sans-serif;padding:40px;color:#1a1816\"><h2>Connected.</h2><p>You can close this tab and go back to Notes AI Capture.</p></body>"
                    let reply = "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: \(html.utf8.count)\r\nConnection: close\r\n\r\n" + html
                    connection.send(content: Data(reply.utf8), completion: .contentProcessed { _ in
                        connection.cancel()
                        if let callback, target.hasPrefix("/callback") {
                            done.resume(.success(callback))
                        } else {
                            done.resume(.failure(MCPOAuth.Failure.badCallback))
                        }
                        listener.cancel()
                    })
                }
            }
            listener.start(queue: queue)
        }
    }

    /// Resume a continuation once, from whichever callback fires first.
    private final class Resumer: @unchecked Sendable {
        private var continuation: CheckedContinuation<URL, Error>?
        private let lock = NSLock()
        init(_ continuation: CheckedContinuation<URL, Error>) { self.continuation = continuation }
        func resume(_ result: Result<URL, Error>) {
            lock.lock(); defer { lock.unlock() }
            continuation?.resume(with: result)
            continuation = nil
        }
    }
}
