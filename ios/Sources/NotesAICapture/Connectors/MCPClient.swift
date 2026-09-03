import Foundation

/// A minimal Model Context Protocol client over the Streamable HTTP
/// transport: JSON-RPC 2.0 POSTed to one URL, replies either as plain JSON
/// or as a short SSE stream. Enough to connect (`initialize`), keep the
/// session id, and list the server's tools — which is what the Connectors
/// tab needs to show that HubSpot, Notion, … are really reachable.
struct MCPClient {
    static let protocolVersion = "2025-06-18"

    struct ServerInfo: Equatable {
        let name: String
        let version: String?
        let protocolVersion: String
        let sessionId: String?
    }

    struct Tool: Codable, Equatable, Identifiable, Sendable {
        let name: String
        let description: String?
        var id: String { name }
    }

    enum Failure: Error, LocalizedError {
        /// 401 from the server; `resourceMetadataURL` is the
        /// `WWW-Authenticate … resource_metadata="…"` hint when present.
        case unauthorized(resourceMetadataURL: URL?)
        case http(Int, String)
        case rpc(code: Int, message: String)
        case badResponse(String)

        var errorDescription: String? {
            switch self {
            case .unauthorized: return "The server wants you to sign in."
            case .http(let code, let body):
                let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
                return "HTTP \(code)" + (trimmed.isEmpty ? "" : ": \(trimmed.prefix(160))")
            case .rpc(let code, let message): return "\(message) (\(code))"
            case .badResponse(let why): return why
            }
        }
    }

    let endpoint: URL
    var bearerToken: String?
    var sessionId: String?
    private let session: URLSession

    init(endpoint: URL, bearerToken: String? = nil, session: URLSession = .shared) {
        self.endpoint = endpoint
        self.bearerToken = bearerToken
        self.session = session
    }

    // MARK: - Handshake

    /// `initialize` + `notifications/initialized`. Returns the server's
    /// identity and stores the session id for the calls that follow.
    mutating func initialize(clientName: String = "Notes AI Capture", clientVersion: String = "1.0") async throws -> ServerInfo {
        let params: [String: Any] = [
            "protocolVersion": Self.protocolVersion,
            "capabilities": [:],
            "clientInfo": ["name": clientName, "version": clientVersion],
        ]
        let (result, headers) = try await call(method: "initialize", params: params)
        if let id = headers["Mcp-Session-Id"] as? String ?? headers["mcp-session-id"] as? String {
            sessionId = id
        }
        let serverInfo = result["serverInfo"] as? [String: Any]
        let info = ServerInfo(
            name: serverInfo?["name"] as? String ?? endpoint.host() ?? "MCP server",
            version: serverInfo?["version"] as? String,
            protocolVersion: result["protocolVersion"] as? String ?? Self.protocolVersion,
            sessionId: sessionId)
        // The "initialized" notification has no id and no reply body.
        try? await notify(method: "notifications/initialized")
        return info
    }

    /// Every tool the server offers (first page is enough for a summary).
    func listTools() async throws -> [Tool] {
        let (result, _) = try await call(method: "tools/list", params: [:])
        guard let tools = result["tools"] as? [[String: Any]] else { return [] }
        return tools.compactMap { raw in
            guard let name = raw["name"] as? String else { return nil }
            return Tool(name: name, description: raw["description"] as? String)
        }
    }

    // MARK: - JSON-RPC

    private func call(method: String, params: [String: Any]) async throws -> ([String: Any], [AnyHashable: Any]) {
        let id = Int(Date().timeIntervalSince1970 * 1000) % 1_000_000
        let body: [String: Any] = ["jsonrpc": "2.0", "id": id, "method": method, "params": params]
        let (bytes, response) = try await post(body)
        guard let message = try await Self.firstMessage(in: bytes, response: response, matching: id) else {
            throw Failure.badResponse("No reply to \(method).")
        }
        if let error = message["error"] as? [String: Any] {
            throw Failure.rpc(code: error["code"] as? Int ?? -1,
                              message: error["message"] as? String ?? "Unknown error")
        }
        return (message["result"] as? [String: Any] ?? [:], response.allHeaderFields)
    }

    private func notify(method: String) async throws {
        let body: [String: Any] = ["jsonrpc": "2.0", "method": method]
        _ = try await post(body)
    }

    /// POST and hand back the response as soon as its headers are in; the
    /// body is read by the caller (an SSE stream may stay open).
    private func post(_ body: [String: Any]) async throws -> (URLSession.AsyncBytes, HTTPURLResponse) {
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 20
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json, text/event-stream", forHTTPHeaderField: "Accept")
        request.setValue(Self.protocolVersion, forHTTPHeaderField: "MCP-Protocol-Version")
        if let bearerToken { request.setValue("Bearer \(bearerToken)", forHTTPHeaderField: "Authorization") }
        if let sessionId { request.setValue(sessionId, forHTTPHeaderField: "Mcp-Session-Id") }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (bytes, raw) = try await session.bytes(for: request)
        guard let response = raw as? HTTPURLResponse else { throw Failure.badResponse("Not an HTTP response.") }
        switch response.statusCode {
        case 200..<300:
            return (bytes, response)
        case 401:
            throw Failure.unauthorized(resourceMetadataURL: Self.resourceMetadataURL(from: response))
        default:
            var data = Data()
            for try await byte in bytes.prefix(4096) { data.append(byte) }
            throw Failure.http(response.statusCode, String(data: data, encoding: .utf8) ?? "")
        }
    }

    /// The JSON-RPC reply with our id, whether the body is one JSON object
    /// or an SSE stream of `data:` lines. Stops reading as soon as it has it.
    private static func firstMessage(in bytes: URLSession.AsyncBytes, response: HTTPURLResponse, matching id: Int) async throws -> [String: Any]? {
        let contentType = (response.value(forHTTPHeaderField: "Content-Type") ?? "").lowercased()
        if contentType.contains("text/event-stream") {
            var payload: [String] = []
            func flush() -> [String: Any]? {
                defer { payload = [] }
                let text = payload.joined(separator: "\n")
                guard !text.isEmpty, let json = text.data(using: .utf8),
                      let object = try? JSONSerialization.jsonObject(with: json) as? [String: Any],
                      matches(object, id: id)
                else { return nil }
                return object
            }
            for try await line in bytes.lines {
                if line.isEmpty {
                    if let message = flush() { return message }
                } else if line.hasPrefix("data:") {
                    payload.append(line.dropFirst(5).trimmingCharacters(in: .whitespaces))
                }
            }
            return flush()
        }
        var data = Data()
        for try await byte in bytes { data.append(byte) }
        guard !data.isEmpty else { return nil }
        let object = try JSONSerialization.jsonObject(with: data)
        if let dict = object as? [String: Any] { return dict }
        if let batch = object as? [[String: Any]] { return batch.first { matches($0, id: id) } }
        return nil
    }

    private static func matches(_ object: [String: Any], id: Int) -> Bool {
        if let got = object["id"] as? Int { return got == id }
        if let got = object["id"] as? String { return got == String(id) }
        return false
    }

    /// `WWW-Authenticate: Bearer resource_metadata="https://…"` (RFC 9728),
    /// the pointer the OAuth flow starts from.
    static func resourceMetadataURL(from response: HTTPURLResponse) -> URL? {
        guard let header = response.value(forHTTPHeaderField: "WWW-Authenticate") else { return nil }
        guard let range = header.range(of: "resource_metadata=") else { return nil }
        var rest = header[range.upperBound...]
        if rest.hasPrefix("\"") { rest = rest.dropFirst() }
        let value = rest.prefix { $0 != "\"" && $0 != "," && $0 != " " }
        return URL(string: String(value))
    }
}
