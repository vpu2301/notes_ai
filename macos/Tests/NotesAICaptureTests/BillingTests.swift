import XCTest
@testable import NotesAICapture

/// The Billing tab's copy. The web twin is `web/tests/billing.test.ts`.
final class BillingTests: XCTestCase {
    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONDecoder().decode(type, from: Data(json.utf8))
    }

    func testTheAIAllowanceIsAShareNeverOurCost() throws {
        let meter = try decode(UsageMeter.self, #"{"key": "ai", "used": 150, "limit": 2000}"#)
        XCTAssertEqual(meter.text, "8% used")
        let over = try decode(UsageMeter.self, #"{"key": "ai", "used": 5000, "limit": 2000}"#)
        XCTAssertEqual(over.text, "100% used")
    }

    func testCountsAgainstTheLimitOrSaysThereIsNone() throws {
        XCTAssertEqual(try decode(UsageMeter.self, #"{"key": "notes", "used": 4, "limit": 50}"#).text, "4 of 50")
        let open = try decode(UsageMeter.self, #"{"key": "members", "used": 7, "limit": null}"#)
        XCTAssertEqual(open.text, "7 · no limit")
        XCTAssertNil(open.share)
    }

    func testFreeAndContactUsPlansAreNamedInWords() throws {
        let plan = { (price: String) in
            try self.decode(BillingPlan.self, """
            {"code": "x", "name": "X", "summary": "", "price_cents": \(price), "currency": "EUR",
             "limits": {}, "features": [], "self_serve": true}
            """)
        }
        XCTAssertEqual(try plan("0").priceText, "Free")
        XCTAssertEqual(try plan("null").priceText, "Talk to us")
        XCTAssertTrue(try plan("1800").priceText.hasSuffix("per member / month"))
    }

    func testYearlyIsPricedPerMonthWithTheYearlyTotal() throws {
        let pro = try decode(BillingPlan.self, """
        {"code": "pro", "name": "Pro", "summary": "", "price_cents": 1800, "yearly_price_cents": 18000,
         "currency": "EUR", "limits": {}, "features": [], "self_serve": true}
        """)
        XCTAssertTrue(pro.priceText(yearly: true).contains("billed yearly"))
        XCTAssertTrue(pro.priceText(yearly: true).contains("180"))
        XCTAssertTrue(pro.priceText(yearly: false).hasSuffix("per member / month"))
    }
}
