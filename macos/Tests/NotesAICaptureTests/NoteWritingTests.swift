import XCTest
@testable import NotesAICapture

/// N3 — Settings › Note writing: the style a run used in its status line, and the style the
/// workspace's instructions ask for.
final class NoteWritingTests: XCTestCase {
    private func view(_ style: String) throws -> GenerationView {
        try JSONDecoder().decode(GenerationView.self, from: Data("""
        {"id": "g1", "status": "complete", "recording_type": "meeting", "writing_style": "\(style)",
         "model_settings_version": 2, "instructions": {"scope": "workspace", "version": 1}}
        """.utf8))
    }

    func testARunInAnotherStyleNamesItFirst() throws {
        XCTAssertEqual(try view("academic").statusLabel,
                       "Academic style · workspace instructions v1 · model settings v2")
    }

    func testTheBusinessStyleIsNotNamed() throws {
        XCTAssertEqual(try view("business").statusLabel, "Workspace instructions v1 · model settings v2")
    }

    func testTheStyleFollowsTheRecordingType() throws {
        let view = try JSONDecoder().decode(GenerationView.self, from: Data("""
        {"id": "g1", "status": "complete", "recording_type": "podcast_broadcast", "writing_style": "formal"}
        """.utf8))
        XCTAssertEqual(view.statusLabel, "Podcast / broadcast · Formal style")
    }

    func testTheInstructionsNameTheirStyle() throws {
        func decode(_ profile: String) throws -> AIInstructions {
            try JSONDecoder().decode(AIInstructions.self, from: Data("""
            {"scope": "workspace", "version": 2, "text": "Write it like a paper.", "profile": \(profile),
             "profile_hash": "ab", "compile_status": "compiled", "compile_error_kind": null,
             "understood": [], "guidance": [], "not_applied": [], "can_edit": false, "max_chars": 8000,
             "updated_at": null, "updated_by": null}
            """.utf8))
        }
        XCTAssertEqual(try decode(#"{"style": "academic", "length": "short"}"#).profileStyle, "academic")
        XCTAssertNil(try decode(#"{"summary_sentences": 4}"#).profileStyle)
        XCTAssertNil(try decode("null").profileStyle)
    }
}
