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
