import Foundation
import Security

// MARK: - Models

/// A remote MCP server the user has added (HubSpot, Notion, a custom one).
/// The URL and status live in UserDefaults; tokens live in the Keychain.
struct Connector: Codable, Identifiable, Equatable, Sendable {
    enum Auth: String, Codable, Sendable {
        /// Sign in through the server's OAuth flow (the default for hosted MCPs).
        case oauth
        /// A static bearer token the user pasted (a private-app token, an API key).
        case token
        /// The server is open (a local dev server).
        case none
    }

    enum Status: Codable, Equatable, Sendable {
        case notConnected
        case connecting
        case connected(tools: Int, server: String)
        case needsSignIn
        case failed(String)
    }

    var id: String
    var presetId: String?
    var name: String
    var url: String
    var auth: Auth
    var status: Status = .notConnected
    var toolNames: [String] = []
    var lastConnectedAt: Date?
    /// OAuth client this app is known as on the server (self-registered,
    /// or the id the user brought). The secret, if any, is in the Keychain.
    var registration: MCPOAuth.Registration?
    /// A client id the user entered for servers without self-registration.
    var clientId: String = ""

    var symbol: String { ConnectorPreset.byId[presetId ?? ""]?.symbol ?? "puzzlepiece.extension" }
    var host: String { URL(string: url)?.host() ?? url }
}

/// The catalogue behind "Add connector". The URLs are the vendors'
/// published remote MCP endpoints; every one of them stays editable in
/// the connector's sheet.
struct ConnectorPreset: Identifiable, Equatable {
    let id: String
    let name: String
    let symbol: String
    let url: String
    let auth: Connector.Auth
    let blurb: String

    static let all: [ConnectorPreset] = [
        .init(id: "hubspot", name: "HubSpot", symbol: "person.2.crop.square.stack",
              url: "https://mcp.hubspot.com/anthropic", auth: .oauth,
              blurb: "Contacts, companies and deals from your CRM."),
        .init(id: "notion", name: "Notion", symbol: "doc.richtext",
              url: "https://mcp.notion.com/mcp", auth: .oauth,
              blurb: "Pages and databases in your workspace."),
        .init(id: "linear", name: "Linear", symbol: "line.3.horizontal.decrease.circle",
              url: "https://mcp.linear.app/mcp", auth: .oauth,
              blurb: "Issues and projects."),
        .init(id: "atlassian", name: "Atlassian", symbol: "square.stack.3d.up",
              url: "https://mcp.atlassian.com/v1/mcp", auth: .oauth,
              blurb: "Jira issues and Confluence pages."),
        .init(id: "custom", name: "Custom MCP server", symbol: "server.rack",
              url: "", auth: .oauth,
              blurb: "Any server that speaks MCP over HTTP."),
    ]

    static let byId: [String: ConnectorPreset] = Dictionary(uniqueKeysWithValues: all.map { ($0.id, $0) })
}

// MARK: - Store

/// The list of connectors and the connect / sign-in / disconnect actions
/// behind the Connectors tab.
@MainActor
final class ConnectorStore: ObservableObject {
    @Published private(set) var connectors: [Connector] = []
    /// Ids with a connect attempt in flight (spinner in the row).
    @Published private(set) var busy: Set<String> = []

    private static let key = "mcpConnectors"

    init() {
        connectors = Self.load()
        // A session does not survive a relaunch; show what we know.
        for index in connectors.indices {
            if case .connected = connectors[index].status, connectors[index].auth == .oauth,
               Keychain.read(account: connectors[index].id) == nil {
                connectors[index].status = .needsSignIn
            }
        }
    }

    // MARK: Editing

    @discardableResult
    func add(preset: ConnectorPreset, name: String? = nil, url: String? = nil, auth: Connector.Auth? = nil) -> Connector {
        let connector = Connector(
            id: UUID().uuidString,
            presetId: preset.id == "custom" ? nil : preset.id,
            name: (name ?? preset.name).trimmingCharacters(in: .whitespaces),
            url: (url ?? preset.url).trimmingCharacters(in: .whitespaces),
            auth: auth ?? preset.auth)
        connectors.append(connector)
        persist()
        return connector
    }

    func update(_ id: String, name: String, url: String, auth: Connector.Auth, token: String?,
                clientId: String = "", clientSecret: String? = nil) {
        guard let index = connectors.firstIndex(where: { $0.id == id }) else { return }
        let trimmedClientId = clientId.trimmingCharacters(in: .whitespaces)
        let changedEndpoint = connectors[index].url != url.trimmingCharacters(in: .whitespaces)
            || connectors[index].auth != auth
            || connectors[index].clientId != trimmedClientId
        connectors[index].name = name.trimmingCharacters(in: .whitespaces)
        connectors[index].url = url.trimmingCharacters(in: .whitespaces)
        connectors[index].auth = auth
        connectors[index].clientId = trimmedClientId
        if auth == .token, let token, !token.isEmpty {
            Keychain.write(account: id, secret: Data(token.utf8))
        }
        if let clientSecret, !clientSecret.isEmpty {
            Keychain.write(account: Self.secretAccount(id), secret: Data(clientSecret.utf8))
        } else if trimmedClientId.isEmpty {
            Keychain.delete(account: Self.secretAccount(id))
        }
        if changedEndpoint {
            connectors[index].registration = nil
            connectors[index].status = .notConnected
            connectors[index].toolNames = []
            if auth != .token { Keychain.delete(account: id) }
        }
        persist()
    }

    func remove(_ id: String) {
        connectors.removeAll { $0.id == id }
        Keychain.delete(account: id)
        Keychain.delete(account: Self.secretAccount(id))
        persist()
    }

    static func secretAccount(_ id: String) -> String { "\(id).client-secret" }

    func storedClientSecret(for id: String) -> String? {
        Keychain.read(account: Self.secretAccount(id)).flatMap { String(data: $0, encoding: .utf8) }
    }

    /// Forget the tokens but keep the entry, so "Connect" starts over.
    func disconnect(_ id: String) {
        guard let index = connectors.firstIndex(where: { $0.id == id }) else { return }
        if connectors[index].auth != .token { Keychain.delete(account: id) }
        connectors[index].status = .notConnected
        connectors[index].toolNames = []
        connectors[index].registration = nil
        persist()
    }

    func storedToken(for id: String) -> String? {
        Keychain.read(account: id).flatMap { String(data: $0, encoding: .utf8) }
    }

    // MARK: Connecting

    /// At launch: quietly re-verify every connector that was connected
    /// before (tokens may have expired; the server may be gone).
    func recheck() async {
        let ids = connectors.filter {
            if case .connected = $0.status { return true }
            return false
        }.map(\.id)
        for id in ids { await connect(id, interactive: false) }
    }

    /// Reach the server, sign in when it asks for it, and record what it
    /// offers. `interactive` allows the browser to open; the automatic
    /// re-check at launch passes false.
    func connect(_ id: String, interactive: Bool = true) async {
        guard let index = connectors.firstIndex(where: { $0.id == id }), !busy.contains(id) else { return }
        guard let endpoint = URL(string: connectors[index].url), endpoint.host() != nil else {
            set(id) { $0.status = .failed("Enter the server's URL first.") }
            return
        }
        busy.insert(id)
        set(id) { $0.status = .connecting }
        defer { busy.remove(id) }

        do {
            var bearer = bearerToken(for: connectors[index])
            if bearer == nil, connectors[index].auth == .token {
                throw Connector.Problem.tokenMissing
            }
            do {
                try await handshake(id, endpoint: endpoint, bearer: bearer)
            } catch MCPClient.Failure.unauthorized(let metadataURL) where connectors[index].auth == .oauth {
                guard interactive else {
                    set(id) { $0.status = .needsSignIn }
                    return
                }
                bearer = try await signIn(id, endpoint: endpoint, resourceMetadataURL: metadataURL)
                try await handshake(id, endpoint: endpoint, bearer: bearer)
            }
        } catch MCPClient.Failure.unauthorized {
            set(id) { $0.status = .needsSignIn }
        } catch MCPOAuth.Failure.cancelled {
            set(id) { $0.status = .needsSignIn }
        } catch {
            set(id) { $0.status = .failed(error.localizedDescription) }
        }
    }

    private func handshake(_ id: String, endpoint: URL, bearer: String?) async throws {
        var client = MCPClient(endpoint: endpoint, bearerToken: bearer)
        let info = try await client.initialize()
        let tools = (try? await client.listTools()) ?? []
        set(id) {
            $0.status = .connected(tools: tools.count, server: info.name)
            $0.toolNames = tools.map(\.name)
            $0.lastConnectedAt = Date()
        }
    }

    /// A usable access token: the pasted one, or the OAuth one (refreshed
    /// when it has expired and the server gave us a refresh token).
    private func bearerToken(for connector: Connector) -> String? {
        switch connector.auth {
        case .none: return nil
        case .token: return storedToken(for: connector.id)
        case .oauth:
            guard let data = Keychain.read(account: connector.id),
                  let tokens = try? JSONDecoder().decode(MCPOAuth.Tokens.self, from: data)
            else { return nil }
            return tokens.accessToken
        }
    }

    private func signIn(_ id: String, endpoint: URL, resourceMetadataURL: URL?) async throws -> String {
        guard let connector = connectors.first(where: { $0.id == id }) else { throw MCPOAuth.Failure.cancelled }
        let clientSecret = storedClientSecret(for: id)
        // First try the refresh token, quietly.
        if let data = Keychain.read(account: id),
           let tokens = try? JSONDecoder().decode(MCPOAuth.Tokens.self, from: data),
           let refresh = tokens.refreshToken,
           var registration = connector.registration {
            registration.clientSecret = clientSecret
            if let fresh = try? await MCPOAuth.refresh(registration, refreshToken: refresh) {
                Keychain.write(account: id, secret: try JSONEncoder().encode(fresh))
                return fresh.accessToken
            }
        }
        var registration: MCPOAuth.Registration
        if let existing = connector.registration {
            registration = existing
        } else {
            let (_, metadata) = try await MCPOAuth.discover(server: endpoint, resourceMetadataURL: resourceMetadataURL)
            registration = try await MCPOAuth.register(
                server: endpoint, metadata: metadata,
                clientId: connector.clientId.isEmpty ? nil : connector.clientId, clientSecret: clientSecret)
            // The secret stays in the Keychain, not in UserDefaults.
            var stored = registration
            stored.clientSecret = nil
            set(id) { $0.registration = stored }
        }
        registration.clientSecret = clientSecret
        let tokens = try await MCPOAuth.authorize(registration)
        Keychain.write(account: id, secret: try JSONEncoder().encode(tokens))
        return tokens.accessToken
    }

    // MARK: Persistence

    private func set(_ id: String, _ change: (inout Connector) -> Void) {
        guard let index = connectors.firstIndex(where: { $0.id == id }) else { return }
        change(&connectors[index])
        persist()
    }

    private func persist() {
        // Transient states are not worth remembering across launches.
        var snapshot = connectors
        for index in snapshot.indices where snapshot[index].status == .connecting {
            snapshot[index].status = .notConnected
        }
        if let data = try? JSONEncoder().encode(snapshot) {
            UserDefaults.standard.set(data, forKey: Self.key)
        }
    }

    private static func load() -> [Connector] {
        guard let data = UserDefaults.standard.data(forKey: key),
              let list = try? JSONDecoder().decode([Connector].self, from: data)
        else { return [] }
        return list
    }
}

extension Connector {
    enum Problem: Error, LocalizedError {
        case tokenMissing
        var errorDescription: String? { "Paste the server's access token first." }
    }
}

// MARK: - Keychain

/// Generic-password items under one service; one per connector id.
enum Keychain {
    private static let service = "ai.notes.capture.connectors"

    static func read(account: String) -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess else { return nil }
        return result as? Data
    }

    static func write(account: String, secret: Data) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        let attributes: [String: Any] = [
            kSecValueData as String: secret,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            SecItemAdd(query.merging(attributes) { $1 } as CFDictionary, nil)
        }
    }

    static func delete(account: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
