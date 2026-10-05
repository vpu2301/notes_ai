import XCTest
@testable import NotesAICapture

/// The unified-spelling banner and tooltip, as the web says them.
final class EntityCorrectionTests: XCTestCase {
    private func correction(_ status: String, _ forms: [String] = ["Andala", "Handela"],
                            source: String = "majority") -> EntityCorrection {
        let json = """
        {"id": "\(UUID().uuidString)", "kind": "entity", "from_forms": [\(forms.map { "\"\($0)\"" }.joined(separator: ","))],
         "to_text": "Handala", "occurrences_count": 3, "source": "\(source)", "confidence": 0.85,
         "status": "\(status)"}
        """
        return try! JSONDecoder().decode(EntityCorrection.self, from: Data(json.utf8))
    }

    func testNoBannerWithoutLiveCorrections() {
        XCTAssertNil(EntityCorrection.banner([], language: "de"))
        XCTAssertNil(EntityCorrection.banner([correction("rejected")], language: "de"))
    }

    func testBannerCountsVariantSpellings() {
        let banner = EntityCorrection.banner([correction("accepted"), correction("proposed", ["Tilda"])], language: "de")
        XCTAssertEqual(banner?.text, "2 Schreibweisen vereinheitlicht · 1 Schreibweisen zu prüfen")
        XCTAssertEqual(banner?.action, "Prüfen")
    }

    func testTooltipNamesTheVariants() {
        XCTAssertEqual(correction("accepted").unifiedFrom(language: "de"), "vereinheitlicht aus: Andala, Handela")
        XCTAssertEqual(EntityCorrection.paragraphHelp("Heute über Handala.", [correction("accepted")], language: "en"),
                       "Handala — unified from: Andala, Handela")
    }
}
