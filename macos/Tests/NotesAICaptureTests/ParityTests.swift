import XCTest
@testable import NotesAICapture

/// Pieces the web client already had: the line key for a generated line's evidence, the fifth settings address, the bell's deep links.
final class ParityTests: XCTestCase {
    /// The same fixtures the web suite reads (`scripts/dev/item_key_fixtures.py`): all clients and the server must key a line identically.
    func testLineKeysMatchTheSharedFixtures() throws {
        let here = URL(fileURLWithPath: #filePath)
        let fixtures = here
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent()
            .appending(path: "web/tests/fixtures/item-keys.json")
        guard let data = try? Data(contentsOf: fixtures) else {
            throw XCTSkip("fixtures not checked out beside macos/")
        }
        struct Row: Decodable { let line: String; let key: String }
        let rows = try JSONDecoder().decode([Row].self, from: data)
        XCTAssertGreaterThan(rows.count, 3)
        for row in rows {
            XCTAssertEqual(GeneratedLineKey.of(row.line), row.key, row.line)
        }
    }

    func testAnOwnerPrefixAndADueTailDoNotChangeTheKey() {
        let bare = GeneratedLineKey.of("- send the pricing proposal")
        XCTAssertEqual(GeneratedLineKey.of("- Anna: send the pricing proposal — by Tuesday"), bare)
        XCTAssertEqual(GeneratedLineKey.of("• Send the pricing proposal."), bare)
    }

    func testSettingsSavedBeforeTheBellStillDecode() throws {
        let json = """
        {"authBaseURL":"http://a","asrBaseURL":"http://b","noteBaseURL":"http://c","webAppURL":"http://d"}
        """
        let settings = try JSONDecoder().decode(BackendSettings.self, from: Data(json.utf8))
        XCTAssertEqual(settings.noteBaseURL, "http://c")
        XCTAssertEqual(settings.notificationBaseURL, BackendSettings.default.notificationBaseURL)
        let again = try JSONDecoder().decode(BackendSettings.self, from: JSONEncoder().encode(settings))
        XCTAssertEqual(again, settings)
    }

    func testANotificationKnowsWhichNoteItPointsAt() throws {
        let json = """
        {"id":"n1","category":"share","title":"t","body_text":"","deep_link":"/notes/abc-123?tab=responses",
         "resource_type":"note","resource_id":null,"severity":"info","read_at":null,
         "created_at":"2026-09-28T12:00:00Z"}
        """
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let item = try decoder.decode(NotificationItem.self, from: Data(json.utf8))
        XCTAssertEqual(item.noteId, "abc-123")
        XCTAssertTrue(item.isUnread)
    }

    func testTheCertaintyChipNamesTheHolder() {
        let json = """
        {"item_key":"k","kind":"fact","section_key":"gen:overview","text":"x","owner_label":null,
         "due_text":null,"due_date":null,"explicit":true,"confidence":1,"flags":[],"quote":"q",
         "start_ms":65000,"end_ms":66000,"speaker_label":null,"speaker_name":"Anna","placement":"placed",
         "certainty":"prediction","attributed_to":"Peter Reinbold"}
        """
        let row = try! JSONDecoder().decode(GeneratedItem.self, from: Data(json.utf8))
        XCTAssertEqual(row.chipLabel, "Forecast · Reinbold")
        XCTAssertEqual(row.timeText, "01:05")
    }
}
