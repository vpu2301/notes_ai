import XCTest
@testable import NotesAICapture

/// The note body's markdown-lite grammar. The web twin of these cases is
/// `web/tests/richText.test.ts`; the two parsers are meant to agree, so a
/// case added on one side belongs on the other.
final class RichTextTests: XCTestCase {
    /// The flat text of a run, ignoring where the emphasis fell.
    private func flat(_ spans: [RichSpan]) -> String {
        spans.map(\.text).joined()
    }

    private func spans(of block: RichBlock) -> [RichSpan] {
        switch block.kind {
        case .heading(_, let spans), .paragraph(let spans), .quote(let spans): return spans
        case .item(let item): return item.spans
        case .rule, .table: return []
        }
    }

    private func items(_ blocks: [RichBlock]) -> [RichListItem] {
        blocks.compactMap { if case .item(let item) = $0.kind { return item } else { return nil } }
    }

    func testEmptyBodyHasNoBlocks() {
        XCTAssertTrue(RichText.parse("").isEmpty)
        XCTAssertTrue(RichText.parse("   \n\n  ").isEmpty)
    }

    func testSoftWrapsJoinAndBlankLinesSplit() {
        let blocks = RichText.parse("one\ntwo\n\nthree")
        XCTAssertEqual(blocks.count, 2)
        XCTAssertEqual(flat(spans(of: blocks[0])), "one two")
        XCTAssertEqual(flat(spans(of: blocks[1])), "three")
    }

    /// h1 and h2 belong to the document's own chrome — its title and the
    /// section name — so the body starts a level down.
    func testBodyHeadingsStartAtH3() {
        let levels = RichText.parse("# Top\n## Under\n###### Deep").map { block -> Int in
            if case .heading(let level, _) = block.kind { return level }
            return 0
        }
        XCTAssertEqual(levels, [3, 4, 4])
    }

    func testIndentationReadsAsNesting() {
        let list = items(RichText.parse("- one\n  - two\n    - three\n- back"))
        XCTAssertEqual(list.map(\.depth), [0, 1, 2, 0])
    }

    func testStrayIndentDoesNotOpenALevelOfItsOwn() {
        let list = items(RichText.parse("- one\n   - two\n- three"))
        XCTAssertEqual(list.map(\.depth), [0, 1, 0])
    }

    func testBulletsNumbersAndCheckboxesAreToldApart() {
        let list = items(RichText.parse("- a\n1. b\n- [x] c\n- [ ] d"))
        XCTAssertEqual(list.map(\.ordered), [false, true, false, false])
        XCTAssertEqual(list.map(\.done), [nil, nil, true, false])
        XCTAssertEqual(list[1].number, 1)
    }

    func testContinuationLineHangsOffTheItemAboveIt() {
        let list = items(RichText.parse("- decision\n  agreed with Denys"))
        XCTAssertEqual(list.count, 1)
        XCTAssertEqual(flat(list[0].spans), "decision agreed with Denys")
    }

    func testRuleIsToldFromABullet() {
        if case .rule = RichText.parse("---")[0].kind {} else { XCTFail("--- should be a rule") }
        XCTAssertEqual(items(RichText.parse("- one")).count, 1)
    }

    func testQuotedLinesFoldIntoOneQuote() {
        let blocks = RichText.parse("> first\n> second")
        XCTAssertEqual(blocks.count, 1)
        XCTAssertEqual(flat(spans(of: blocks[0])), "first second")
    }

    func testPipeTableDropsTheDashedRow() {
        let blocks = RichText.parse("| a | b |\n| --- | --- |\n| 1 | 2 |")
        guard case .table(let head, let rows) = blocks[0].kind else { return XCTFail("expected a table") }
        XCTAssertEqual(head.map(flat), ["a", "b"])
        XCTAssertEqual(rows.map { $0.map(flat) }, [["1", "2"]])
    }

    func testInlineEmphasis() {
        let runs = RichText.spans("plain **bold** and *soft* and `code`")
        XCTAssertEqual(runs.map(\.text), ["plain ", "bold", " and ", "soft", " and ", "code"])
        XCTAssertEqual(runs.map(\.bold), [false, true, false, false, false, false])
        XCTAssertEqual(runs.map(\.italic), [false, false, false, true, false, false])
        XCTAssertEqual(runs.map(\.code), [false, false, false, false, false, true])
    }

    /// An identifier is not emphasis — `note_service_id` is a name.
    func testUnderscoreInsideAWordIsLeftAlone() {
        XCTAssertEqual(RichText.spans("note_service_id"), [RichSpan(text: "note_service_id")])
    }

    func testUnclosedMarkerStaysText() {
        XCTAssertEqual(RichText.spans("**not closed"), [RichSpan(text: "**not closed")])
    }

    func testPreviewTakesTheFirstLineWithWordsInIt() {
        XCTAssertEqual(RichText.preview("## Heading\n- **Vertical 1**: comms"), "Heading")
        XCTAssertEqual(RichText.preview("- **Vertical 1**: comms"), "Vertical 1: comms")
        XCTAssertEqual(RichText.preview(String(repeating: "x", count: 300), limit: 10),
                       String(repeating: "x", count: 9) + "…")
        XCTAssertEqual(RichText.preview(""), "")
    }

    /// Cyrillic is the common case here, and NSRegularExpression works in
    /// UTF-16 units — a body that starts in Ukrainian must not lose a
    /// character to an offset computed against the wrong length.
    func testNonLatinTextSurvivesTheSpanSplit() {
        let runs = RichText.spans("Вертикаль 1: **комунікаційна** система")
        XCTAssertEqual(runs.map(\.text), ["Вертикаль 1: ", "комунікаційна", " система"])
        XCTAssertEqual(flat(runs), "Вертикаль 1: комунікаційна система")
    }
}
