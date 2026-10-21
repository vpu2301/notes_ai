import XCTest
@testable import NotesAICapture

/// The workspace's note instructions as `GET /v1/ai/instructions` sends them (read-only here),
/// and the instructions version a run followed.
final class NoteInstructionsTests: XCTestCase {
    /// The OpenAPI `InstructionsView` shape, with every field the server sends.
    private let stored = """
    {"scope": "workspace", "version": 3,
     "text": "# Length\\nShort. Four summary sentences at most.\\nAlways write in English.",
     "profile": {"length": "short", "summary_sentences": 4}, "profile_hash": "ab12",
     "compile_status": "compiled", "compile_error_kind": null,
     "understood": ["Shorter than standard — about 60 % of the usual length.",
                    "The summary has at most 4 sentences."],
     "guidance": ["Write for a reader who has thirty seconds."],
     "not_applied": [{"text": "Always write in English", "reason": "language_locked",
                      "message": "Notes are written in the language spoken in the meeting."}],
     "can_edit": false, "max_chars": 8000,
     "updated_at": "2026-10-19T10:00:00Z", "updated_by": "7f1c"}
    """

    func testTheStoredInstructionsDecode() throws {
        let i = try JSONDecoder().decode(AIInstructions.self, from: Data(stored.utf8))
        XCTAssertEqual(i.version, 3)
        XCTAssertTrue(i.text.hasPrefix("# Length"))
        XCTAssertFalse(i.canEdit)
        XCTAssertEqual(i.maxChars, 8000)
    }

    /// P2a: `source` says whether the text is the default rules or the workspace's own;
    /// a server without it (older) leaves it nil, which is not "default".
    func testTheSourceDecodes() throws {
        let i = try JSONDecoder().decode(AIInstructions.self, from: Data("""
        {"scope": "workspace", "version": 0, "text": "Write what was said.", "profile": {},
         "profile_hash": "e3", "compile_status": "compiled", "compile_error_kind": null,
         "understood": [], "guidance": [], "not_applied": [], "can_edit": true,
         "max_chars": 12000, "updated_at": null, "updated_by": null,
         "source": "default", "default_text": "Write what was said."}
        """.utf8))
        XCTAssertEqual(i.source, "default")
        XCTAssertTrue(i.isDefault)
        let old = try JSONDecoder().decode(AIInstructions.self, from: Data(stored.utf8))
        XCTAssertNil(old.source)
        XCTAssertFalse(old.isDefault)
    }

    func testNoInstructionsDecode() throws {
        let i = try JSONDecoder().decode(AIInstructions.self, from: Data("""
        {"scope": "workspace", "version": 0, "text": "", "profile": {}, "profile_hash": "e3",
         "compile_status": "compiled", "compile_error_kind": null, "understood": [],
         "guidance": [], "not_applied": [], "can_edit": true, "max_chars": 8000,
         "updated_at": null, "updated_by": null}
        """.utf8))
        XCTAssertEqual(i.version, 0)
        XCTAssertNil(i.updatedAt)
    }

    func testARunUnderInstructionsSaysWhichVersion() throws {
        let view = try JSONDecoder().decode(GenerationView.self, from: Data("""
        {"id": "g1", "status": "complete", "sections_written": 3, "recording_type": "podcast_broadcast",
         "instructions": {"scope": "workspace", "version": 3}}
        """.utf8))
        XCTAssertEqual(view.instructions, InstructionsRef(scope: "workspace", version: 3))
        XCTAssertEqual(view.statusLabel, "Podcast / broadcast · workspace instructions v3")
    }

    func testAMeetingHasOnlyTheInstructionsInItsLine() throws {
        let view = try JSONDecoder().decode(GenerationView.self, from: Data("""
        {"id": "g1", "status": "complete", "recording_type": "meeting",
         "instructions": {"scope": "workspace", "version": 1}}
        """.utf8))
        XCTAssertEqual(view.statusLabel, "Workspace instructions v1")
    }

    func testARunWithoutInstructionsSaysNothingAboutThem() throws {
        for json in [#"{"id": "g1", "status": "complete", "instructions": null}"#,
                     #"{"id": "g1", "status": "complete"}"#] {
            let view = try JSONDecoder().decode(GenerationView.self, from: Data(json.utf8))
            XCTAssertNil(view.instructions)
            XCTAssertNil(view.statusLabel)
        }
    }

    // MARK: - N4: per-note and per-meeting-type instructions

    func testANoteBodyDecodesWithItsBasesAndParent() throws {
        let i = try JSONDecoder().decode(AIInstructions.self, from: Data("""
        {"scope": "note", "version": 1, "text": "Bullets only.", "profile": {}, "profile_hash": "c4",
         "compile_status": "compiled", "compile_error_kind": null, "understood": ["Bullets only."],
         "guidance": [], "not_applied": [], "can_edit": true, "max_chars": 8000,
         "updated_at": "2026-10-19T10:00:00Z", "updated_by": "7f1c",
         "base_versions": {"workspace": 3, "client": 1},
         "extends": {"scope": "client", "version": 1}, "stale": false, "scopes": []}
        """.utf8))
        XCTAssertEqual(i.baseVersions, ["workspace": 3, "client": 1])
        XCTAssertEqual(i.extends, InstructionsRef(scope: "client", version: 1))
        XCTAssertEqual(i.maxChars, 8000)
    }

    func testTheStatusLineNamesTheScope() throws {
        func label(_ instructions: String) throws -> String? {
            try JSONDecoder().decode(GenerationView.self, from: Data("""
            {"id": "g1", "status": "complete", "recording_type": "meeting", "instructions": \(instructions)}
            """.utf8)).statusLabel
        }
        XCTAssertEqual(try label(#"{"scope": "client", "version": 2}"#), "Client-call instructions v2")
        XCTAssertEqual(try label(#"{"scope": "one_on_one", "version": 1}"#), "1:1 instructions v1")
        XCTAssertEqual(try label(#"{"scope": "note", "version": 1}"#), "This note's instructions")
        XCTAssertEqual(try label(#"{"scope": "sales", "version": 4, "fallback": "stale"}"#),
                       "Sales-call instructions v4 (workspace instructions used — the sales-call text is being updated)")
    }

    func testAStaleFallbackDecodes() throws {
        let ref = try JSONDecoder().decode(InstructionsRef.self, from: Data("""
        {"scope": "team", "version": 2, "fallback": "stale"}
        """.utf8))
        XCTAssertEqual(ref, InstructionsRef(scope: "team", version: 2, fallback: "stale"))
        XCTAssertNil(try JSONDecoder().decode(InstructionsRef.self,
                                              from: Data(#"{"scope": "workspace", "version": 1}"#.utf8)).fallback)
    }
}

/// The model settings, read-only on this platform (P2: only what the writer reads).
final class ModelSettingsDecodingTests: XCTestCase {
    func testTheSettingsCarryTheVersionAndEffectiveParameters() throws {
        let json = """
        {"provider": "platform", "tier": "standard", "generation_enabled": true,
         "effective_provider": "platform", "effective_tier": "standard", "processors": [],
         "needs_acknowledgement": [], "month_to_date_cents": 0, "budget_cents": 2000,
         "may_choose_premium": true, "can_edit": false,
         "model_params_version": 2,
         "model_params_effective": {"temperature": 0.4, "max_output_tokens": null,
           "max_concurrency": 2, "ask_temperature": 0.2, "ask_max_tokens": 700}}
        """
        let s = try JSONDecoder().decode(AISettings.self, from: Data(json.utf8))
        XCTAssertEqual(s.modelParamsVersion, 2)
        XCTAssertEqual(s.modelParamsEffective?.temperature, 0.4)
        XCTAssertNil(s.modelParamsEffective?.maxOutputTokens)
        XCTAssertEqual(s.modelParamsEffective?.maxConcurrency, 2)
    }

    func testAnOlderServerStillDecodes() throws {
        let json = """
        {"provider": "platform", "tier": "standard", "generation_enabled": true,
         "effective_provider": "platform", "effective_tier": "standard", "processors": [],
         "needs_acknowledgement": [], "month_to_date_cents": 0, "budget_cents": 2000,
         "may_choose_premium": true, "can_edit": false}
        """
        let s = try JSONDecoder().decode(AISettings.self, from: Data(json.utf8))
        XCTAssertNil(s.modelParamsVersion)
        XCTAssertNil(s.modelParamsEffective)
    }

    func testARunNamesTheModelSettingsVersion() throws {
        let view = try JSONDecoder().decode(GenerationView.self, from: Data("""
        {"id": "g1", "status": "complete", "recording_type": "meeting", "model_settings_version": 2,
         "instructions": {"scope": "workspace", "version": 1}}
        """.utf8))
        XCTAssertEqual(view.statusLabel, "Workspace instructions v1 · model settings v2")
    }

    func testAStaleFallbackAsTheWorkerRecordsIt() {
        let ref = InstructionsRef(scope: "workspace", version: 3, fallback: "stale")
        XCTAssertEqual(ref.statusText,
                       "workspace instructions v3 (workspace instructions used — the meeting type's text is being updated)")
    }
}
