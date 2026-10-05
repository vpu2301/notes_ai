import XCTest
@testable import NotesAICapture

/// What the engine made of a recording, decoded from `GET …/generation` in the web client's words.
final class GenerationViewTests: XCTestCase {
    private func decode(_ json: String) throws -> GenerationView {
        try JSONDecoder().decode(GenerationView.self, from: Data(json.utf8))
    }

    func testTheFieldsDecodeWhenPresent() throws {
        let view = try decode("""
        {"id": "g1", "status": "complete", "sections_written": 3,
         "recording_type": "podcast_broadcast", "recording_type_source": "classifier",
         "language": "en",
         "excluded_ranges": [{"start_ms": 45000, "end_ms": 52000, "reason": "background"}]}
        """)
        XCTAssertEqual(view.recordingType, "podcast_broadcast")
        XCTAssertEqual(view.recordingTypeSource, "classifier")
        XCTAssertEqual(view.excludedRanges, [ExcludedRange(startMs: 45000, endMs: 52000, reason: "background")])
        XCTAssertEqual(view.recordingTypeLabel, "Podcast / broadcast")
        XCTAssertEqual(view.excludedItems.map(\.text), ["00:45–00:52 (background speech)"])
    }

    func testAnOlderRunWithoutThemStillDecodes() throws {
        let view = try decode(#"{"id": "g1", "status": "complete", "sections_written": 2}"#)
        XCTAssertNil(view.recordingType)
        XCTAssertNil(view.recordingTypeSource)
        XCTAssertNil(view.excludedRanges)
        XCTAssertNil(view.recordingTypeLabel)
        XCTAssertTrue(view.excludedItems.isEmpty)
    }

    func testNullsDecodeAsAbsent() throws {
        let view = try decode("""
        {"id": "g1", "status": "complete", "recording_type": null,
         "recording_type_source": null, "excluded_ranges": [], "language": null}
        """)
        XCTAssertNil(view.recordingTypeLabel)
        XCTAssertTrue(view.shownExcluded.items.isEmpty)
    }

    func testAnUnknownReasonIsAPassage() throws {
        let view = try decode("""
        {"id": "g1", "status": "complete",
         "excluded_ranges": [{"start_ms": 61000, "end_ms": 65500, "reason": "cosmic_rays"}]}
        """)
        XCTAssertEqual(view.excludedItems.map(\.text), ["01:01–01:05 (a passage)"])
    }

    func testMeetingAndUnknownTypesHaveNoLabel() {
        XCTAssertNil(GenerationView.recordingTypeLabel("meeting"))
        XCTAssertNil(GenerationView.recordingTypeLabel("other"))
        XCTAssertNil(GenerationView.recordingTypeLabel(nil))
        XCTAssertEqual(GenerationView.recordingTypeLabel("one_on_one"), "One-on-one")
        XCTAssertEqual(GenerationView.recordingTypeLabel("lecture_webinar"), "Lecture / webinar")
    }

    func testReasonsAreNamedInTheSpokenLanguage() {
        XCTAssertEqual(GenerationView.noiseLabel("background", language: "de"), "Hintergrundgespräch")
        XCTAssertEqual(GenerationView.noiseLabel("duplicate", language: "uk"), "повторений уривок")
        XCTAssertEqual(GenerationView.noiseLabel("other_language", language: "fr"),
                       "a passage in another language")
    }

    func testRangesAreInTimeOrderAndCappedAtFour() throws {
        let ranges = (0..<6).reversed().map { i in
            #"{"start_ms": \#(i * 10_000), "end_ms": \#(i * 10_000 + 5_000), "reason": "duplicate"}"#
        }
        let view = try decode(#"{"id": "g1", "status": "partial", "excluded_ranges": [\#(ranges.joined(separator: ","))]}"#)
        let shown = view.shownExcluded
        XCTAssertEqual(shown.items.count, 4)
        XCTAssertEqual(shown.more, 2)
        XCTAssertEqual(shown.items.first?.text, "00:00–00:05 (a duplicated passage)")
        XCTAssertEqual(shown.items.map(\.startMs), [0, 10_000, 20_000, 30_000])
    }

    func testMinutesAreNotWrappedIntoHours() {
        XCTAssertEqual(GenerationView.mmss(3_723_999), "62:03")
        XCTAssertEqual(GenerationView.mmss(-5), "00:00")
    }
}
