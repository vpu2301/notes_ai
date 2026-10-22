import XCTest
@testable import NotesAICapture

/// Telemetry sprint 4: "Export diagnostics…" fetches the recording's newest run and its report.
final class DiagnosticsExportTests: XCTestCase {
    private let recording = "11111111-1111-1111-1111-111111111111"
    private let newest = "22222222-2222-2222-2222-222222222222"
    private let report = Data("# Diagnostics — recording x\n\n## 1. Run identity\n".utf8)

    func testTheNewestRunsReportComesBackAsAMarkdownFile() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
        let (recording, newest, report) = (recording, newest, report)
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/v1/telemetry/recordings/\(recording)/runs":
                return (200, Fixtures.json(["runs": [
                    ["processing_run_id": newest, "recording_id": recording, "kind": "reprocess"],
                    ["processing_run_id": "33333333-3333-3333-3333-333333333333",
                     "recording_id": recording, "kind": "initial"],
                ]]), [:])
            case "/v1/telemetry/runs/\(newest)/report.md":
                return (200, report, ["Content-Type": "text/markdown; charset=utf-8"])
            default:
                return (404, Fixtures.json(["detail": "not found"]), [:])
            }
        }

        let got = try await client.latestDiagnostics(recordingId: recording)

        XCTAssertEqual(got.filename, "diagnostics-\(recording)-\(newest).md")
        XCTAssertEqual(got.data, report)
        let fetch = StubServer.requests(to: "/v1/telemetry/runs/\(newest)/report.md").first
        XCTAssertEqual(fetch?.headers["Accept"], "text/markdown")
        XCTAssertTrue(StubServer.requests.allSatisfy { !$0.path.contains("/transcript") })
    }

    func testARecordingWithoutRunsSaysSo() async {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (200, Fixtures.json(["runs": [] as [Any]]), [:])
        }

        do {
            _ = try await client.latestDiagnostics(recordingId: recording)
            XCTFail("expected noRuns")
        } catch {
            XCTAssertEqual(error as? DiagnosticsError, .noRuns)
            XCTAssertEqual(error.localizedDescription, "No diagnostics for this recording yet.")
        }
    }
}
