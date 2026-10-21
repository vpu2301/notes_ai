import XCTest
@testable import NotesAICapture

/// Sprint B4 — a generated line's provenance and a claim row's verdict decode and label in the note's language.
final class ProvenanceTests: XCTestCase {
    func testProvenanceAndVerdictDecodeAndLabel() throws {
        let json = """
        {"item_key":"k1","kind":"claim","section_key":"claims","text":"| Trump | Briefwahl | unbelegt | 06:41 |",
         "owner_label":null,"due_text":null,"due_date":null,"explicit":true,"confidence":0.9,"flags":[],
         "quote":"die Briefwahl werde manipuliert, was unbelegt ist","start_ms":401000,"end_ms":405000,
         "speaker_label":"SPEAKER_1","speaker_name":null,"placement":"written","cites":["f1","f2"],
         "provenance":"composed","verdict":"unbelegt"}
        """
        let row = try JSONDecoder().decode(GeneratedItem.self, from: Data(json.utf8))
        XCTAssertEqual(row.provenance, "composed")
        XCTAssertEqual(row.verdict, "unbelegt")
        XCTAssertEqual(row.provenanceLabel(language: "de"), "Aus 2 Aussagen")
        XCTAssertEqual(row.provenanceLabel(language: "uk"), "З 2 висловлювань")
        XCTAssertEqual(row.provenanceLabel(language: nil), "From 2 statements")
    }

    func testRowsWrittenBeforeB4HaveNoMarker() throws {
        let json = """
        {"item_key":"k2","kind":"topic_bullet","section_key":"gen:x","text":"- x","owner_label":null,
         "due_text":null,"due_date":null,"explicit":true,"confidence":0.9,"flags":[],"quote":"x",
         "start_ms":0,"end_ms":1000,"speaker_label":null,"speaker_name":null,"placement":"written"}
        """
        let row = try JSONDecoder().decode(GeneratedItem.self, from: Data(json.utf8))
        XCTAssertNil(row.provenance)
        XCTAssertNil(row.provenanceLabel(language: "de"))
        XCTAssertEqual(NoteLabels.provenance(language: "de", provenance: "verbatim", count: 1), "Wörtlich")
    }
}

/// P3 — the cited turns and the check verdict on a row, and what a row without a cite is.
final class CitedTurnsTests: XCTestCase {
    private let base = """
    "item_key":"k1","kind":"bullet","section_key":"gen:overview","text":"a line","owner_label":null,
    "due_text":null,"due_date":null,"explicit":true,"confidence":1.0,"flags":[],"quote":"the words",
    "start_ms":45000,"end_ms":52000,"speaker_label":"SPEAKER_1","speaker_name":"Anna","placement":"written"
    """

    func testTheTurnsDecodeAndTheFirstIsTheQuote() throws {
        let json = "{" + base + """
        ,"cites":["turn:12","turn:41"],"cited_turns":[
          {"turn":12,"start_ms":45000,"end_ms":52000,"speaker":"Anna","text":"the words"},
          {"turn":41,"start_ms":754000,"end_ms":760000,"speaker":null,"text":"later words"}],
        "cite_nearest":true,"check":"unsupported","check_reason":"not said"}
        """
        let row = try JSONDecoder().decode(GeneratedItem.self, from: Data(json.utf8))
        XCTAssertEqual(row.turnsCited.map(\.turn), [12, 41])
        XCTAssertEqual(row.turnsCited.first?.text, "the words")
        XCTAssertNil(row.turnsCited.last?.speaker)
        XCTAssertTrue(row.hasReference && row.isUnsupported)
        XCTAssertEqual(row.checkReason, "not said")
        XCTAssertEqual(row.citeNearest, true)
    }

    func testAnOlderRowFallsBackToItsQuoteAndANoCiteRowHasNoReference() throws {
        let older = try JSONDecoder().decode(GeneratedItem.self, from: Data(("{" + base + ",\"cites\":[\"f1\"]}").utf8))
        XCTAssertEqual(older.turnsCited.map(\.text), ["the words"])
        XCTAssertEqual(older.turnsCited.first?.startMs, 45000)
        XCTAssertFalse(older.isUnsupported)
        let bare = try JSONDecoder().decode(GeneratedItem.self, from: Data(("{" + base + ",\"cites\":[]}").utf8))
        XCTAssertFalse(bare.hasReference)
        XCTAssertTrue(bare.turnsCited.isEmpty)
        XCTAssertNil(bare.check)
    }
}
