import XCTest
@testable import NotesAICapture

/// The app's "Meeting <date>" placeholder is sent as no title, so the note can be named from what was said; a typed title is sent as typed.
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
