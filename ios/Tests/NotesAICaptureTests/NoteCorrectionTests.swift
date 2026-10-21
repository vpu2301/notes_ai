import XCTest
@testable import NotesAICapture

/// Sprint A3 — the note's respellings shown over the transcript ("heard as"), whole words only.
final class NoteCorrectionTests: XCTestCase {
    private let quill = NoteCorrection(surface: "Quilhaven", canonical: "Quillhaven", source: "glossary", count: 2)

    func testDecodesTheSummary() throws {
        let json = """
        [{"surface":"Quilhaven","canonical":"Quillhaven","source":"glossary","count":2}]
        """
        let rows = try JSONDecoder().decode([NoteCorrection].self, from: Data(json.utf8))
        XCTAssertEqual(rows, [quill])
    }

    func testSubstitutesWholeWordsAndUnderlinesThem() {
        let out = NoteCorrection.substituted("In Quilhaven, not Quilhavens.", [quill])
        XCTAssertEqual(String(out!.characters), "In Quillhaven, not Quilhavens.")
        let marked = out!.runs.filter { $0.underlineStyle != nil }.map { String(out![$0.range].characters) }
        XCTAssertEqual(marked, ["Quillhaven"])
        XCTAssertNil(NoteCorrection.substituted("Nothing here.", [quill]))
    }

    func testHelpAndLabelsFollowTheLanguage() {
        XCTAssertEqual(NoteCorrection.paragraphHelp("In Quilhaven.", [quill], language: "de"),
                       "Quillhaven — gehört als: Quilhaven")
        XCTAssertEqual(NoteLabels.asTranscribed(language: "uk"), "Показати як транскрибовано")
        XCTAssertEqual(NoteLabels.heardAs(language: nil), "heard as")
    }
}
