import XCTest
@testable import NotesAICapture

/// Which side of a call a speaker was heard on, and names from the microphone channel.
final class CallSidesTests: XCTestCase {
    func testResultSidesAndSourcesDecodeAndOlderResultsStillDo() throws {
        let result = try JSONDecoder().decode(TranscriptResult.self, from: Data("""
        {"job_id":"j1","segments":[],
         "speaker_sides":{"SPEAKER_1":"local","SPEAKER_2":"remote"},
         "speaker_name_sources":{"SPEAKER_1":"channel"}}
        """.utf8))
        XCTAssertEqual(result.speakerSides, ["SPEAKER_1": "local", "SPEAKER_2": "remote"])
        XCTAssertEqual(result.speakerNameSources, ["SPEAKER_1": "channel"])
        let old = try JSONDecoder().decode(TranscriptResult.self, from: Data(#"{"job_id":"j1","segments":[]}"#.utf8))
        XCTAssertNil(old.speakerSides)
        XCTAssertNil(old.speakerNameSources)
    }

    func testTheSideGlyphAndTheChannelMarker() {
        let sides = ["SPEAKER_1": "local", "SPEAKER_2": "remote", "SPEAKER_3": "sideways"]
        XCTAssertEqual(SpeakerChannelMarkers.side(of: "SPEAKER_1", in: sides), .local)
        XCTAssertEqual(SpeakerChannelMarkers.side(of: "SPEAKER_2", in: sides), .remote)
        XCTAssertNil(SpeakerChannelMarkers.side(of: "SPEAKER_3", in: sides))
        XCTAssertNil(SpeakerChannelMarkers.side(of: "SPEAKER_1", in: [:]), "mono jobs show nothing")
        XCTAssertEqual(SpeakerSide.remote.accessibilityLabel, "On the call audio")

        let sources = ["SPEAKER_1": "channel", "SPEAKER_2": "typed"]
        XCTAssertTrue(SpeakerChannelMarkers.isChannelNamed("SPEAKER_1", sources: sources))
        XCTAssertFalse(SpeakerChannelMarkers.isChannelNamed("SPEAKER_2", sources: sources))
        XCTAssertEqual(SpeakerChannelMarkers.sources(sources, afterRenaming: "SPEAKER_1", sent: nil)["SPEAKER_1"],
                       "cleared")
    }
}
