import Foundation

/// Async URLSession client for the Notes AI backends.
///
/// - The HttpOnly refresh cookie set by `POST /auth/login` lives in the
///   session's default cookie storage and is attached automatically.
/// - The short-lived access token is kept in memory only, and refreshed
///   once (via `POST /auth/refresh`) whenever a request answers 401 or the
///   token is about to expire.
actor APIClient {
    private var settings: BackendSettings
    private var accessToken: String?
    private var tokenExpiry: Date?
    private let session: URLSession

    init(settings: BackendSettings) {
        self.settings = settings
        let config = URLSessionConfiguration.default
        config.httpCookieStorage = .shared
        config.httpShouldSetCookies = true
        config.timeoutIntervalForRequest = 120
        self.session = URLSession(configuration: config)
    }

    func update(settings: BackendSettings) {
        self.settings = settings
    }

    // MARK: - Auth

    func login(email: String, password: String, otp: String?) async throws {
        var body: [String: String] = ["email": email, "password": password]
        if let otp, !otp.isEmpty { body["otp"] = otp }
        let data = try await send(
            base: \.authBaseURL, path: "/auth/login", method: "POST",
            jsonBody: try JSONSerialization.data(withJSONObject: body),
            authorized: false
        )
        try store(loginResponse: data)
    }

    /// Try to mint a fresh access token from the stored refresh cookie.
    /// Returns `false` when there is no valid session.
    func restoreSession() async -> Bool {
        do {
            try await refresh()
            return true
        } catch {
            return false
        }
    }

    func logout() async {
        _ = try? await send(base: \.authBaseURL, path: "/auth/logout", method: "POST",
                            authorized: true, allowRefresh: false)
        accessToken = nil
        tokenExpiry = nil
    }

    private func refresh() async throws {
        let data = try await send(base: \.authBaseURL, path: "/auth/refresh", method: "POST",
                                  authorized: false)
        try store(loginResponse: data)
    }

    private func store(loginResponse data: Data) throws {
        let response = try decode(LoginResponse.self, from: data)
        accessToken = response.accessToken
        tokenExpiry = Date().addingTimeInterval(TimeInterval(response.expiresIn))
    }

    // MARK: - Templates & notes (note-service)

    func fetchTemplates() async throws -> [TemplateSummary] {
        let data = try await send(base: \.noteBaseURL, path: "/templates", method: "GET",
                                  authorized: true)
        return try decode([TemplateSummary].self, from: data)
    }

    func createNoteFromTranscript(asrJobId: String, templateId: String?, title: String) async throws -> FromTranscriptResponse {
        let request = FromTranscriptRequest(asrJobId: asrJobId, templateId: templateId, title: title)
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/from-transcript", method: "POST",
                                  jsonBody: try JSONEncoder().encode(request), authorized: true)
        return try decode(FromTranscriptResponse.self, from: data)
    }

    // MARK: - Notes (note-service): open, edit, finalize, export

    func fetchNote(id: String) async throws -> NoteEnvelope {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)", method: "GET",
                                  query: [("include_content", "true")], authorized: true)
        return try decode(NoteEnvelope.self, from: data)
    }

    func fetchTemplate(id: String) async throws -> TemplateDetail {
        let data = try await send(base: \.noteBaseURL, path: "/templates/\(id)", method: "GET",
                                  authorized: true)
        return try decode(TemplateDetail.self, from: data)
    }

    func updateDraft(id: String, content: NoteContent, expectedVersion: Int) async throws -> UpdateDraftResponse {
        let request = UpdateDraftRequest(content: content, expectedVersion: expectedVersion)
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/draft", method: "PUT",
                                  jsonBody: try JSONEncoder().encode(request), authorized: true)
        return try decode(UpdateDraftResponse.self, from: data)
    }

    func finalizeNote(id: String, expectedVersion: Int) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["expected_version": expectedVersion])
        _ = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/finalize", method: "POST",
                           jsonBody: body, authorized: true)
    }

    func revertToDraft(id: String) async throws {
        _ = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/revert-to-draft", method: "POST",
                           authorized: true)
    }

    /// The tenant's notes, newest first; `q` runs the server's full-text
    /// search (with synonym expansion).
    func searchNotes(query: String?, limit: Int = 100) async throws -> SearchResponse {
        var params: [(String, String)] = [("limit", String(limit))]
        if let query, !query.isEmpty { params.append(("q", query)) }
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/search", method: "GET",
                                  query: params, authorized: true)
        return try decode(SearchResponse.self, from: data)
    }

    func notePDF(id: String) async throws -> Data {
        try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/pdf", method: "GET",
                       accept: "application/pdf", authorized: true)
    }

    // MARK: - Delete, visibility, sharing (0016)

    func deleteNote(id: String) async throws {
        _ = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)", method: "DELETE", authorized: true)
    }

    func sharing(id: String) async throws -> SharingView {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/sharing", method: "GET",
                                  authorized: true)
        return try decode(SharingView.self, from: data)
    }

    func setVisibility(id: String, visibility: String) async throws -> SharingView {
        let body = try JSONSerialization.data(withJSONObject: ["visibility": visibility])
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/visibility", method: "PUT",
                                  jsonBody: body, authorized: true)
        return try decode(SharingView.self, from: data)
    }

    /// Idempotent: returns the note's live link, minting one if needed.
    func createPublicLink(id: String) async throws -> SharingView {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/public-link", method: "POST",
                                  authorized: true)
        return try decode(SharingView.self, from: data)
    }

    func revokePublicLink(id: String) async throws -> SharingView {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/public-link", method: "DELETE",
                                  authorized: true)
        return try decode(SharingView.self, from: data)
    }

    /// 404 `not_a_member` when nobody in the workspace has that address.
    func shareWithMember(id: String, email: String) async throws -> SharingView {
        let body = try JSONSerialization.data(withJSONObject: ["email": email])
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/share", method: "POST",
                                  jsonBody: body, authorized: true)
        return try decode(SharingView.self, from: data)
    }

    // MARK: - Transcription jobs (asr-service)

    /// Plaintext transcript of a COMPLETE job (409 while it is still running).
    func transcript(jobId: String) async throws -> TranscriptResult {
        let data = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(jobId)/result", method: "GET",
                                  authorized: true)
        return try decode(TranscriptResult.self, from: data)
    }

    func submitJob(fileURL: URL, contentType: String, language: String, diarize: Bool) async throws -> TranscriptionJob {
        let audioData = try Data(contentsOf: fileURL)
        let boundary = "NotesAICapture-\(UUID().uuidString)"
        let body = Self.multipartBody(
            boundary: boundary,
            fields: [("language", language), ("diarize", diarize ? "true" : "false")],
            fileField: "audio",
            fileName: fileURL.lastPathComponent,
            contentType: contentType,
            fileData: audioData
        )
        let data = try await send(base: \.asrBaseURL, path: "/asr/jobs", method: "POST",
                                  body: body,
                                  contentType: "multipart/form-data; boundary=\(boundary)",
                                  authorized: true)
        return try decode(TranscriptionJob.self, from: data)
    }

    func jobStatus(id: String) async throws -> TranscriptionJob {
        let data = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(id)", method: "GET",
                                  authorized: true)
        return try decode(TranscriptionJob.self, from: data)
    }

    // MARK: - Core request machinery

    private func send(
        base: KeyPath<BackendSettings, String>,
        path: String,
        method: String,
        query: [(String, String)] = [],
        jsonBody: Data? = nil,
        body: Data? = nil,
        contentType: String? = nil,
        accept: String = "application/json",
        authorized: Bool,
        allowRefresh: Bool = true
    ) async throws -> Data {
        guard let root = URL(string: settings[keyPath: base].trimmingCharacters(in: .whitespaces)) else {
            throw APIError.badURL
        }
        if authorized, allowRefresh, let expiry = tokenExpiry, expiry.timeIntervalSinceNow < 30 {
            // Token expired or about to; refresh proactively (failures fall
            // through to the 401 retry below).
            try? await refresh()
        }

        var url = root.appending(path: path)
        if !query.isEmpty {
            url.append(queryItems: query.map { URLQueryItem(name: $0.0, value: $0.1) })
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue(accept, forHTTPHeaderField: "Accept")
        if let jsonBody {
            request.httpBody = jsonBody
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        } else if let body {
            request.httpBody = body
            if let contentType {
                request.setValue(contentType, forHTTPHeaderField: "Content-Type")
            }
        }
        if authorized, let token = accessToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.http(status: 0, problem: nil)
        }

        if http.statusCode == 401, authorized, allowRefresh {
            try await refresh()
            return try await send(base: base, path: path, method: method, query: query,
                                  jsonBody: jsonBody, body: body, contentType: contentType,
                                  accept: accept, authorized: authorized, allowRefresh: false)
        }

        guard (200..<300).contains(http.statusCode) else {
            let problem = try? JSONDecoder().decode(Problem.self, from: data)
            throw APIError.http(status: http.statusCode, problem: problem)
        }
        return data
    }

    /// Server timestamps are ISO 8601, with or without fractional seconds.
    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let raw = try decoder.singleValueContainer().decode(String.self)
            let fractional = ISO8601DateFormatter()
            fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            let plain = ISO8601DateFormatter()
            plain.formatOptions = [.withInternetDateTime]
            if let date = fractional.date(from: raw) ?? plain.date(from: raw) { return date }
            throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath,
                                                    debugDescription: "Unrecognised date: \(raw)"))
        }
        return decoder
    }()

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try Self.decoder.decode(type, from: data)
        } catch {
            throw APIError.http(status: 0, problem: Problem(
                title: "Unexpected response",
                detail: "Could not read the server's response.",
                status: nil, code: nil))
        }
    }

    // MARK: - Multipart

    static func multipartBody(
        boundary: String,
        fields: [(String, String)],
        fileField: String,
        fileName: String,
        contentType: String,
        fileData: Data
    ) -> Data {
        var body = Data()
        func append(_ string: String) { body.append(Data(string.utf8)) }

        for (name, value) in fields {
            append("--\(boundary)\r\n")
            append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n")
            append("\(value)\r\n")
        }
        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"\(fileField)\"; filename=\"\(fileName)\"\r\n")
        append("Content-Type: \(contentType)\r\n\r\n")
        body.append(fileData)
        append("\r\n--\(boundary)--\r\n")
        return body
    }
}
