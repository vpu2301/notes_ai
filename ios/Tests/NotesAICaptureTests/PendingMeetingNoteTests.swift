import XCTest
@testable import NotesAICapture

/// The scratchpad must not lose a character: on disk, survives a relaunch,
/// right workspace, merges rather than overwrites.
final class PendingMeetingNoteTests: XCTestCase {
    private var dir: URL!

    override func setUpWithError() throws {
        dir = FileManager.default.temporaryDirectory
            .appending(path: "meeting-notes-tests-\(UUID().uuidString)")
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: dir)
    }

    private func note(_ capture: String = "cap-1", identity: String = "me",
                      text: String = "budget 40k", noteId: String? = nil,
                      startedAt: Date = Date(timeIntervalSince1970: 1_700_000_000),
                      lineTimes: [String: Int] = [:]) -> PendingMeetingNote {
        PendingMeetingNote(
            clientCaptureId: capture, noteId: noteId, title: "Weekly", language: "auto",
            meetingType: "auto", startedAt: startedAt, text: text, lineTimes: lineTimes,
            calendar: nil, identityId: identity, tenantId: "t-1", updatedAt: Date())
    }

    // MARK: - Survival

    func testATypedLineSurvivesTheProcessThatTypedIt() {
        PendingMeetingNotes.save(note(text: "Tom hesitated here"), in: dir)
        // A fresh read, as a relaunch would do it: nothing in memory.
        let back = PendingMeetingNotes.load("cap-1", in: dir)
        XCTAssertEqual(back?.text, "Tom hesitated here")
        XCTAssertEqual(back?.tenantId, "t-1")
    }

    func testSavingTwiceReplacesRatherThanDuplicates() {
        PendingMeetingNotes.save(note(text: "one line"), in: dir)
        PendingMeetingNotes.save(note(text: "one line\ntwo lines"), in: dir)
        XCTAssertEqual(PendingMeetingNotes.all(in: dir).count, 1)
        XCTAssertEqual(PendingMeetingNotes.load("cap-1", in: dir)?.text, "one line\ntwo lines")
    }

    func testLineTimesRideAlong() {
        let saved = note(lineTimes: ["aaa": 4_000, "bbb": 90_000])
        PendingMeetingNotes.save(saved, in: dir)
        let times = PendingMeetingNotes.load("cap-1", in: dir)?.pendingLineTimes ?? []
        // Oldest first: the order they should be replayed in.
        XCTAssertEqual(times.map(\.offsetMs), [4_000, 90_000])
    }

    func testSyncOrderIsOldestMeetingFirst() {
        PendingMeetingNotes.save(
            note("later", startedAt: Date(timeIntervalSince1970: 2_000)), in: dir)
        PendingMeetingNotes.save(
            note("earlier", startedAt: Date(timeIntervalSince1970: 1_000)), in: dir)
        XCTAssertEqual(PendingMeetingNotes.all(in: dir).map(\.clientCaptureId),
                       ["earlier", "later"])
    }

    // MARK: - Whose notes they are

    func testAPhoneTwoPeopleShareNeverOffersTheOthersMeeting() {
        PendingMeetingNotes.save(note("cap-1", identity: "me"), in: dir)
        PendingMeetingNotes.save(note("cap-2", identity: "someone-else"), in: dir)
        XCTAssertEqual(PendingMeetingNotes.all(identityId: "me", in: dir).map(\.clientCaptureId),
                       ["cap-1"])
    }

    func testSignOutForgetsThisIdentitysNotesAndNobodyElses() {
        PendingMeetingNotes.save(note("cap-1", identity: "me"), in: dir)
        PendingMeetingNotes.save(note("cap-2", identity: "someone-else"), in: dir)
        XCTAssertEqual(SignOutCleanup.forgetMeetingNotes(identityId: "me", in: dir), 1)
        XCTAssertNil(PendingMeetingNotes.load("cap-1", in: dir))
        XCTAssertNotNil(PendingMeetingNotes.load("cap-2", in: dir))
    }

    func testRemovingOneLeavesTheRest() {
        PendingMeetingNotes.save(note("cap-1"), in: dir)
        PendingMeetingNotes.save(note("cap-2"), in: dir)
        PendingMeetingNotes.remove("cap-1", in: dir)
        XCTAssertEqual(PendingMeetingNotes.all(in: dir).map(\.clientCaptureId), ["cap-2"])
    }

    // MARK: - Merging two devices

    func testMergeAppendsUnderADividerAndNeverOverwrites() {
        let merged = PendingMeetingNotes.merge(remote: "typed on the Mac",
                                               local: "typed on the phone")
        XCTAssertEqual(merged, "typed on the Mac\n\n---\ntyped on the phone")
    }

    func testMergeKeepsWhicheverSideIsTheOnlyOne() {
        XCTAssertEqual(PendingMeetingNotes.merge(remote: "theirs", local: "   "), "theirs")
        XCTAssertEqual(PendingMeetingNotes.merge(remote: "", local: "mine"), "mine")
        XCTAssertEqual(PendingMeetingNotes.merge(remote: "same", local: "same"), "same")
    }

    func testMergeDoesNotDuplicateALineTheServerAlreadyHas() {
        // A reconnect re-sends; the divider must not fill the note with copies.
        let merged = PendingMeetingNotes.merge(remote: "- Ask about budget\nTom hesitated",
                                               local: "ask about budget.\nnew thought")
        XCTAssertEqual(merged, "- Ask about budget\nTom hesitated\n\n---\nnew thought")
    }

    func testMergeOfAnAlreadySyncedScratchpadChangesNothing() {
        let text = "budget 40k\nTom hesitated"
        XCTAssertEqual(PendingMeetingNotes.merge(remote: text, local: text), text)
    }

    // MARK: - Line identity

    func testALineKeepsItsKeyAcrossBulletCaseAndSpacing() {
        XCTAssertEqual(MeetingLineKey.of("- Ask about budget"),
                       MeetingLineKey.of("ask   about  budget."))
        XCTAssertEqual(MeetingLineKey.of("1. Hiring"), MeetingLineKey.of("Hiring"))
    }

    func testABlankLineHasNoKey() {
        XCTAssertEqual(MeetingLineKey.of("   "), "")
        XCTAssertEqual(MeetingLineKey.of("- "), "")
    }

    func testTheKeyIsSixteenHexCharactersAndCarriesNoContent() {
        let key = MeetingLineKey.of("budget forty thousand euros")
        XCTAssertEqual(key.count, 16)
        XCTAssertNotNil(key.range(of: "^[0-9a-f]{16}$", options: .regularExpression),
                        "the key is lowercase hex, and nothing else")
        XCTAssertFalse(key.contains("budget"))
    }

    func testDifferentLinesGetDifferentKeys() {
        XCTAssertNotEqual(MeetingLineKey.of("budget"), MeetingLineKey.of("hiring"))
    }

    // MARK: - Lines

    func testBlankLinesAreNotLines() {
        XCTAssertEqual(PendingMeetingNotes.lines(of: "a\n\n  \nb"), ["a", "b"])
    }
}
