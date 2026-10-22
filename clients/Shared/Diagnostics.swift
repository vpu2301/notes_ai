import Foundation

/// "Export diagnostics…" (telemetry sprint 4): the processing report of a recording's newest
/// run, as the Markdown file the server renders. Timings and counts only — no content.
struct TelemetryRunRef: Decodable, Equatable, Sendable {
    let processingRunId: String
    let recordingId: String

    enum CodingKeys: String, CodingKey {
        case processingRunId = "processing_run_id", recordingId = "recording_id"
    }

    /// The name the server's download carries.
    var reportFilename: String { "diagnostics-\(recordingId)-\(processingRunId).md" }
}

struct TelemetryRunsResponse: Decodable, Sendable {
    let runs: [TelemetryRunRef]
}

enum DiagnosticsError: LocalizedError, Equatable {
    case noRuns

    var errorDescription: String? { "No diagnostics for this recording yet." }
}
