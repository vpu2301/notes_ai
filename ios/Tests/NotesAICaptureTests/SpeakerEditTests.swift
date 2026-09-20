import XCTest
@testable import NotesAICapture

/// Sprint 28 — speaker merge/undo: wire decoding and refusal copy.
final class SpeakerEditTests: XCTestCase {
    func testResultDecodesTalkTimeAndEdits() throws {
        let json = """
        {"job_id":"j1","segments":[],"speakers":["SPEAKER_1","SPEAKER_2"],
         "speaker_names":{"SPEAKER_1":"Anna","SPEAKER_2":"Speaker 2"},"turns":[],
         "speaker_stats":[{"label":"SPEAKER_1","speech_ms":300000,"share":0.96,"turns":4},
                          {"label":"SPEAKER_2","speech_ms":7000,"share":0.04,"turns":1}],
         "result_rev":1,
         "edits":[{"id":"e1","kind":"merge","from_label":"SPEAKER_3","to_label":"SPEAKER_1","created_at":"2026-09-19T10:00:00Z"}]}
        """
        let result = try JSONDecoder().decode(TranscriptResult.self, from: Data(json.utf8))
        XCTAssertEqual(result.speakerStats?.map(\.label), ["SPEAKER_1", "SPEAKER_2"])
        XCTAssertEqual(result.edits?.first?.fromLabel, "SPEAKER_3")
        XCTAssertEqual(result.resultRev, 1)
        XCTAssertFalse(result.speakerStats![0].isSmall)
        XCTAssertTrue(result.speakerStats![1].isSmall)
    }

    func testOlderTranscriptsWithoutStatsStillDecode() throws {
        let json = #"{"job_id":"j1","segments":[],"speakers":["SPEAKER_1"],"turns":[]}"#
        let result = try JSONDecoder().decode(TranscriptResult.self, from: Data(json.utf8))
        XCTAssertNil(result.speakerStats)
    }

    func testRefusalsBecomeTypedErrors() {
        func http(_ code: String) -> Error {
            APIError.http(status: 409, problem: Problem(title: nil, detail: "x", status: 409, code: code))
        }
        XCTAssertEqual(SpeakerEditError.from(http("edit_not_latest")) as? SpeakerEditError, .notLatest)
        XCTAssertEqual(SpeakerEditError.from(http("job_not_complete")) as? SpeakerEditError, .notComplete)
        XCTAssertEqual(SpeakerEditError.from(http("unknown_label")) as? SpeakerEditError, .unknownLabel)
        XCTAssertNil(SpeakerEditError.from(http("something_else")) as? SpeakerEditError)
    }

    func testSpokeFormatsShortAndLongTalk() {
        XCTAssertEqual(spoke(7_000), "7 s")
        XCTAssertEqual(spoke(180_000), "3 min")
    }
}
