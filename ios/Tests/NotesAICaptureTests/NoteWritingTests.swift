import XCTest
@testable import NotesAICapture

/// P2 — Settings › Note writing: the template a run used in its status line, the writer's
/// templates as `GET /v1/ai/templates` sends them, and the model parameters the writer reads.
final class NoteWritingTests: XCTestCase {
    private func view(_ template: String) throws -> GenerationView {
        try JSONDecoder().decode(GenerationView.self, from: Data("""
        {"id": "g1", "status": "complete", "recording_type": "meeting", "template": "\(template)",
         "model_settings_version": 2, "instructions": {"scope": "workspace", "version": 1}}
        """.utf8))
    }

    func testARunNamesItsTemplateFirst() throws {
        XCTAssertEqual(try view("public_meeting").statusLabel,
                       "Public meeting template · workspace instructions v1 · model settings v2")
        XCTAssertEqual(try view("client_call").templateLabel, "Client call")
    }

    func testAutoAndOlderRunsNameNoTemplate() throws {
        XCTAssertEqual(try view("auto").statusLabel, "Workspace instructions v1 · model settings v2")
        let older = try JSONDecoder().decode(GenerationView.self, from: Data("""
        {"id": "g1", "status": "complete", "recording_type": "meeting", "template": null}
        """.utf8))
        XCTAssertNil(older.template)
        XCTAssertNil(older.statusLabel)
    }

    func testTheTemplateFollowsTheRecordingType() throws {
        let view = try JSONDecoder().decode(GenerationView.self, from: Data("""
        {"id": "g1", "status": "complete", "recording_type": "podcast_broadcast", "template": "broadcast"}
        """.utf8))
        XCTAssertEqual(view.statusLabel, "Podcast / broadcast · Broadcast template")
    }

    func testTheSevenTemplatesHaveLabels() {
        XCTAssertEqual(NoteTemplate.allCases.map(\.rawValue),
                       ["auto", "meeting", "client_call", "interview", "broadcast", "public_meeting", "memo"])
        XCTAssertEqual(NoteTemplate.allCases.map(\.label),
                       ["Automatic", "Meeting", "Client call", "Interview", "Broadcast", "Public meeting", "Memo"])
    }

    func testTheTemplateListDecodes() throws {
        let list = try JSONDecoder().decode([WorkspaceTemplate].self, from: Data("""
        [{"name": "meeting", "language": "de", "source": "workspace", "markdown": "## Beschlüsse",
          "can_edit": false, "updated_at": "2026-10-21T10:00:00Z", "updated_by": "7f1c"},
         {"name": "memo", "language": "de", "source": "builtin", "markdown": "## Kern",
          "can_edit": false, "updated_at": null, "updated_by": null}]
        """.utf8))
        XCTAssertEqual(list.map(\.label), ["Meeting", "Memo"])
        XCTAssertEqual(list.map(\.isCustomised), [true, false])
        XCTAssertEqual(list.first?.updatedAt, "2026-10-21T10:00:00Z")
    }

    func testTheAdvancedRowsAreOnlyWhatTheWriterReads() throws {
        let p = try JSONDecoder().decode(AISettings.ModelParams.self, from: Data("""
        {"temperature": 0.4, "max_output_tokens": 4096, "max_concurrency": 2,
         "ask_temperature": 0.2, "ask_max_tokens": 700}
        """.utf8))
        XCTAssertEqual(NoteWritingView.rows(p).map(\.0),
                       ["Temperature", "Output budget", "Parallel calls",
                        "“Ask this note” temperature", "“Ask this note” answer length"])
        XCTAssertEqual(NoteWritingView.rows(p)[1].1, "\(4096.formatted()) tokens")
    }

    func testTheStartRequestCarriesTheTemplateOnlyWhenChosen() throws {
        func body(_ template: String?) throws -> [String: String] {
            let request = StartMeetingRequest(clientCaptureId: "c1", title: nil, startedAt: "2026-10-21T10:00:00Z",
                                              language: nil, meetingType: "auto", template: template, calendar: nil)
            let json = try JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as! [String: Any]
            return json.compactMapValues { $0 as? String }
        }
        XCTAssertEqual(try body("interview")["template"], "interview")
        XCTAssertNil(try body(nil)["template"])
    }
}
