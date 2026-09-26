import XCTest
@testable import NotesAICapture

/// 0057 — the app's "Meeting <date>" placeholder is sent to the server as
/// no title at all, so the note can be named from what was said. A title a
/// person typed is sent as typed.
final class PlaceholderTitleTests: XCTestCase {
    func testThePlaceholderIsRecognised() {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        let placeholder = "Meeting \(formatter.string(from: Date(timeIntervalSince1970: 1_790_000_000)))"
        XCTAssertTrue(CaptureViewModel.isPlaceholderTitle(placeholder))
    }

    func testTypedTitlesAreNot() {
        XCTAssertFalse(CaptureViewModel.isPlaceholderTitle("Meeting with Anna"))
        XCTAssertFalse(CaptureViewModel.isPlaceholderTitle("Q4 Product Roadmap"))
        XCTAssertFalse(CaptureViewModel.isPlaceholderTitle(""))
    }
}
