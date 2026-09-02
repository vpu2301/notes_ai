import Foundation

// MARK: - Backend configuration

struct BackendSettings: Codable, Equatable, Sendable {
    var authBaseURL: String
    var asrBaseURL: String
    var noteBaseURL: String
    var webAppURL: String

    static let `default` = BackendSettings(
        authBaseURL: "http://localhost:8000",
        asrBaseURL: "http://localhost:8001",
        noteBaseURL: "http://localhost:8006",
        webAppURL: "http://localhost:5173"
    )
}

// MARK: - Auth (auth-service)

struct LoginResponse: Decodable, Sendable {
    let accessToken: String
    let expiresIn: Int

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case expiresIn = "expires_in"
    }
}

// MARK: - Batch transcription (asr-service)

enum JobStatus: String, Codable, Sendable {
    case queued, running, complete, failed, cancelled

    var isTerminal: Bool {
        switch self {
        case .complete, .failed, .cancelled: return true
        case .queued, .running: return false
        }
    }

    var label: String {
        switch self {
        case .queued: return "Queued"
        case .running: return "Transcribing"
        case .complete: return "Done"
        case .failed: return "Failed"
        case .cancelled: return "Cancelled"
        }
    }
}

/// Subset of `TranscriptionJobView` this app needs.
struct TranscriptionJob: Decodable, Sendable {
    let id: String
    let status: JobStatus
    let errorMessage: String?
    let errorKind: String?

    enum CodingKeys: String, CodingKey {
        case id, status
        case errorMessage = "error_message"
        case errorKind = "error_kind"
    }

    /// Human-readable failure text (`error_message` is documented as safe to show).
    var failureText: String {
        var text = errorMessage ?? "Transcription failed."
        if let kind = errorKind, !kind.isEmpty {
            text += " (\(kind))"
        }
        return text
    }
}

// MARK: - Templates & notes (note-service)

struct TemplateSummary: Decodable, Sendable {
    let id: String
    let code: String
    let name: String
    let language: String
}

struct FromTranscriptRequest: Encodable, Sendable {
    let asrJobId: String
    let templateId: String?
    let title: String

    enum CodingKeys: String, CodingKey {
        case asrJobId = "asr_job_id"
        case templateId = "template_id"
        case title
    }
}

struct FromTranscriptResponse: Decodable, Sendable {
    let id: String
    let code: String

    enum CodingKeys: String, CodingKey {
        case id, code
    }
}

// MARK: - RFC 9457 problem body

struct Problem: Decodable, Sendable {
    let title: String?
    let detail: String?
    let status: Int?
    let code: String?
}

enum APIError: LocalizedError {
    case badURL
    case http(status: Int, problem: Problem?)
    case notAuthenticated

    var errorDescription: String? {
        switch self {
        case .badURL:
            return "Invalid backend URL — check Settings."
        case .notAuthenticated:
            return "Signed out — please sign in again."
        case .http(let status, let problem):
            var message = problem?.detail ?? problem?.title ?? "Request failed (HTTP \(status))."
            if let code = problem?.code, !code.isEmpty {
                message += " [\(code)]"
            }
            return message
        }
    }

    /// The auth service answers 401 with a problem hinting a one-time code is needed.
    var isMFARequired: Bool {
        guard case .http(let status, let problem) = self, status == 401 else { return false }
        let haystack = [problem?.code, problem?.title, problem?.detail]
            .compactMap { $0?.lowercased() }
            .joined(separator: " ")
        return haystack.contains("mfa") || haystack.contains("otp") || haystack.contains("one-time")
    }
}

// MARK: - Recent captures (persisted locally)

struct RecentCapture: Codable, Identifiable, Equatable, Sendable {
    var jobId: String
    var title: String
    var createdAt: Date
    var status: JobStatus?
    var noteId: String?
    var errorMessage: String?

    var id: String { jobId }
}
