import XCTest
@testable import NotesAICapture

/// Sprint TQ2 T4: music / silence / noise markers render as their own
/// lines in the spoken language, unknown kinds as noise, and between turns
/// without becoming turns.
final class TranscriptNoiseTests: XCTestCase {
    private func noise(_ start: Int, _ end: Int, _ kind: String) -> TranscriptNoise {
        let json = #"{"start_ms": \#(start), "end_ms": \#(end), "kind": "\#(kind)"}"#
        return try! JSONDecoder().decode(TranscriptNoise.self, from: Data(json.utf8))
    }

    func testTheThreeKindsInEachLanguage() {
        let marks = [noise(12_000, 41_000, "music"), noise(61_000, 70_000, "silence"), noise(90_000, 96_000, "noise")]
        XCTAssertEqual(marks.map { $0.line(language: "de") },
                       ["[Musik 00:12–00:41]", "[Stille 01:01–01:10]", "[Geräusch 01:30–01:36]"])
        XCTAssertEqual(marks.map { $0.line(language: "en") },
                       ["[Music 00:12–00:41]", "[Silence 01:01–01:10]", "[Noise 01:30–01:36]"])
        XCTAssertEqual(marks.map { $0.line(language: "uk") },
                       ["[Музика 00:12–00:41]", "[Тиша 01:01–01:10]", "[Шум 01:30–01:36]"])
    }

    func testAnUnknownKindIsNoise() {
        XCTAssertEqual(noise(0, 5_000, "applause").line(language: "en"), "[Noise 00:00–00:05]")
    }
}
