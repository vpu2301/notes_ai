import XCTest
@testable import NotesAICapture

/// Sprint 35 — nothing is remembered without being asked, and what IS
/// remembered is worth remembering.
final class GlossaryTests: XCTestCase {

    // MARK: - What counts as a correction

    func testANameTypedOverAPlaceholderIsWorthRemembering() {
        XCTAssertTrue(RememberableName.worthRemembering(from: "Speaker 2", to: "John Mayer"))
    }

    func testAMishearingCorrectedIsWorthRemembering() {
        XCTAssertTrue(RememberableName.worthRemembering(from: "Jon Meyer", to: "John Mayer"))
    }

    func testClearingANameBackToAPlaceholderTeachesNothing() {
        XCTAssertFalse(RememberableName.worthRemembering(from: "John Mayer", to: "Speaker 2"))
        XCTAssertFalse(RememberableName.worthRemembering(from: "John Mayer", to: "speaker  10"))
    }

    func testCaseAndSpacingAloneTeachNothing() {
        XCTAssertFalse(RememberableName.worthRemembering(from: "john mayer", to: "John Mayer"))
        XCTAssertFalse(RememberableName.worthRemembering(from: "John  Mayer ", to: "John Mayer"))
    }

    func testNamesOutsideTheSizeRulesAreNotOffered() {
        XCTAssertFalse(RememberableName.worthRemembering(from: "Speaker 2", to: "J"))
        XCTAssertFalse(RememberableName.worthRemembering(from: "Speaker 2",
                                                         to: String(repeating: "x", count: 81)))
    }

    /// The server refuses these; not offering them at all is friendlier
    /// than a banner explaining why.
    func testInvisibleCharactersThatMakeOneNameRenderAsAnotherAreRefused() {
        XCTAssertFalse(RememberableName.worthRemembering(from: "Speaker 2", to: "John\u{202e}Mayer"))
        XCTAssertFalse(RememberableName.worthRemembering(from: "Speaker 2", to: "Jo\u{200b}hn"))
        XCTAssertFalse(RememberableName.worthRemembering(from: "Speaker 2", to: "John\u{0007}"))
        XCTAssertFalse(RememberableName.worthRemembering(from: "Speaker 2", to: "John\u{2069}"))
    }

    func testAnOrdinaryNameWithPunctuationIsFine() {
        XCTAssertTrue(RememberableName.worthRemembering(from: "Speaker 1", to: "Anna-Lena O'Brien"))
        XCTAssertTrue(RememberableName.worthRemembering(from: "Speaker 1", to: "Олена Ковальчук"))
    }

    // MARK: - What the old spelling is recorded as

    func testAPreviousNameIsRecordedAsAMishearing() {
        XCTAssertEqual(RememberableName.heardAs("Jon Meyer"), "Jon Meyer")
    }

    func testAPlaceholderIsNotAMishearing() {
        // "Speaker 2" was never a guess at the name; teaching it would
        // make the transcriber worse, not better.
        XCTAssertEqual(RememberableName.heardAs("Speaker 2"), "")
        XCTAssertEqual(RememberableName.heardAs(""), "")
    }

    func testPlaceholderDetection() {
        XCTAssertTrue(RememberableName.isPlaceholder("Speaker 2"))
        XCTAssertTrue(RememberableName.isPlaceholder("speaker 12"))
        XCTAssertFalse(RememberableName.isPlaceholder("Speaker Mayer"))
        XCTAssertFalse(RememberableName.isPlaceholder("Speakerphone"))
        XCTAssertFalse(RememberableName.isPlaceholder("Speaker"))
    }

    // MARK: - The upload carries the workspace's spellings

    func testTheVocabularyHintRidesTheUpload() {
        let fields = APIClient.jobFields(language: "auto", diarize: true, speakersExpected: nil,
                                         context: nil, vocabularyHint: "John Mayer, Contoso")
        XCTAssertEqual(fields.first { $0.0 == "vocabulary_hint" }?.1, "John Mayer, Contoso")
    }

    func testAnEmptyHintIsNotSentAtAll() {
        for hint in [nil, ""] as [String?] {
            let fields = APIClient.jobFields(language: "auto", diarize: true,
                                             speakersExpected: nil, context: nil,
                                             vocabularyHint: hint)
            XCTAssertNil(fields.first { $0.0 == "vocabulary_hint" })
        }
    }

    func testTheHintIsCappedAtTheServersLimit() {
        let fields = APIClient.jobFields(language: "auto", diarize: true, speakersExpected: nil,
                                         context: nil,
                                         vocabularyHint: String(repeating: "a", count: 5000))
        XCTAssertEqual(fields.first { $0.0 == "vocabulary_hint" }?.1.count, 2000)
    }

    // MARK: - Wire shapes

    /// The app's own decoder is private; this mirrors its date strategy
    /// so the test proves the SHAPE, not the decoder.
    private func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let raw = try decoder.singleValueContainer().decode(String.self)
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime]
            guard let date = formatter.date(from: raw) else {
                throw DecodingError.dataCorrupted(
                    .init(codingPath: decoder.codingPath, debugDescription: "bad date"))
            }
            return date
        }
        return decoder
    }

    func testATermDecodesFromTheServersShape() throws {
        let json = """
        {"id":"t-1","term":"John Mayer","kind":"person","heard_as":["Jon Meyer"],
         "created_at":"2026-09-20T09:00:00Z","can_delete":true}
        """
        let term = try decoder().decode(GlossaryTerm.self, from: Data(json.utf8))
        XCTAssertEqual(term.term, "John Mayer")
        XCTAssertEqual(term.kind, .person)
        XCTAssertEqual(term.heardAs, ["Jon Meyer"])
        XCTAssertTrue(term.canDelete)
    }

    func testTheRequestUsesTheServersFieldNames() throws {
        let body = RememberTermRequest(term: "John Mayer", kind: "person", heardAs: ["Jon Meyer"])
        let json = String(decoding: try JSONEncoder().encode(body), as: UTF8.self)
        XCTAssertTrue(json.contains("\"heard_as\""))
        XCTAssertFalse(json.contains("heardAs"))
    }
}
