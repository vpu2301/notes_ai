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

    // MARK: - Transcription jobs (asr-service)

    func submitJob(fileURL: URL, language: String, diarize: Bool) async throws -> TranscriptionJob {
        let audioData = try Data(contentsOf: fileURL)
        let boundary = "NotesAICapture-\(UUID().uuidString)"
        let body = Self.multipartBody(
            boundary: boundary,
            fields: [("language", language), ("diarize", diarize ? "true" : "false")],
            fileField: "audio",
            fileName: fileURL.lastPathComponent,
            contentType: "audio/mp4",
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
        jsonBody: Data? = nil,
        body: Data? = nil,
        contentType: String? = nil,
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

        var request = URLRequest(url: root.appending(path: path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
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
            return try await send(base: base, path: path, method: method,
                                  jsonBody: jsonBody, body: body, contentType: contentType,
                                  authorized: authorized, allowRefresh: false)
        }

        guard (200..<300).contains(http.statusCode) else {
            let problem = try? JSONDecoder().decode(Problem.self, from: data)
            throw APIError.http(status: http.statusCode, problem: problem)
        }
        return data
    }

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try JSONDecoder().decode(type, from: data)
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
