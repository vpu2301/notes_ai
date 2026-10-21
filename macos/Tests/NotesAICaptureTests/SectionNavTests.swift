import XCTest
@testable import NotesAICapture

/// The note's section navigator: which section is current for a scroll position.
final class SectionNavTests: XCTestCase {
    private let items = ["summary", "scope", "review", "completion"].map {
        SectionNavView.Item(key: $0, title: $0.capitalized)
    }

    func testTheFirstSectionIsCurrentAtTheTop() {
        let tops: [String: CGFloat] = ["summary": 200, "scope": 600, "review": 1100, "completion": 1600]
        XCTAssertEqual(SectionNavView.current(items, tops: tops, viewHeight: 800), "summary")
    }

    func testTheLastSectionPastTheLineIsCurrent() {
        let tops: [String: CGFloat] = ["summary": -900, "scope": -300, "review": 80, "completion": 700]
        XCTAssertEqual(SectionNavView.current(items, tops: tops, viewHeight: 800), "review")
    }

    func testTheLastSectionIsCurrentOnceItStartsInTheUpperHalf() {
        let tops: [String: CGFloat] = ["summary": -1400, "scope": -800, "review": -200, "completion": 300]
        XCTAssertEqual(SectionNavView.current(items, tops: tops, viewHeight: 800), "completion")
    }

    private func turn(_ minute: Double, _ speaker: String = "SPEAKER_00", _ text: String = "We should move the launch to next week") -> TranscriptTurn {
        let ms = Int(minute * 60_000)
        return TranscriptTurn(speaker: speaker, name: nil, startMs: ms, endMs: ms + 20_000, paragraphs: [text])
    }

    func testAShortTranscriptIsMarkedEveryMinute() {
        let turns = [0, 0.5, 1.2, 1.4, 2.1, 3.0].map { turn($0) }
        let items = SectionNavView.transcriptItems(turns) { _ in "Anna" }
        XCTAssertEqual(items.map(\.key), ["t0", "t72000", "t126000", "t180000"])
        XCTAssertEqual(items[1].title, "1:12 · Anna — We should move the launch to…")
    }

    func testALongMeetingGetsAtMostTwelveMarksAtARoundInterval() {
        let turns = stride(from: 0.0, through: 95.0, by: 0.25).map { turn($0) }
        let items = SectionNavView.transcriptItems(turns) { _ in nil }
        XCTAssertLessThanOrEqual(items.count, 12)
        // 95 minutes → every 10 minutes: 0:00, 10:00, …, 1:30:00.
        XCTAssertEqual(items.count, 10)
        XCTAssertTrue(items[9].title.hasPrefix("1:30:00 — "))
    }

    func testNoTurnsNoMarks() {
        XCTAssertTrue(SectionNavView.transcriptItems([]) { _ in nil }.isEmpty)
    }
}
