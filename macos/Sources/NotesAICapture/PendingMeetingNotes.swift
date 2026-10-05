import Foundation

/// What the author typed during a meeting, before the server had it.
///
/// The recording survives a crash because `PendingCaptures` moves the audio
/// somewhere safe. The typing had nowhere to survive at all: it lived in a
/// view model and died with the process. This is its `PendingCaptures` —
/// written to disk on every change (debounced), keyed by the capture, and
/// replayed when there is a network again.
///
/// A meeting cannot be typed twice either.
struct PendingMeetingNote: Codable, Equatable, Sendable {
    /// The idempotency key of the capture this belongs to. Also the file
    /// name, so two devices never collide and a retry never duplicates.
    var clientCaptureId: String
    /// The note, once the server has opened one. Nil means it still has to
    /// be created — `startMeeting` failed, or the app was offline.
    var noteId: String?
    var title: String
    var language: String
    var meetingType: String
    /// Recording t=0, for the line offsets below.
    var startedAt: Date
    /// Exactly what was typed. Never trimmed, never reflowed.
    var text: String
    /// `line_key → offset_ms`, first keystroke wins.
    var lineTimes: [String: Int]
    /// The invite's people and agenda, so a capture started from a calendar
    /// event in airplane mode still opens with them.
    var calendar: MeetingCalendarContext?
    /// Who was signed in, and where it goes. A phone handed round a team
    /// must not sync one person's meeting into another's workspace.
    var identityId: String
    var tenantId: String?
    var updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case title, language, text, calendar
        case clientCaptureId = "client_capture_id"
        case noteId = "note_id"
        case meetingType = "meeting_type"
        case startedAt = "started_at"
        case lineTimes = "line_times"
        case identityId = "identity_id"
        case tenantId = "tenant_id"
        case updatedAt = "updated_at"
    }

    /// The timings the server has not seen, in the shape it takes.
    var pendingLineTimes: [UserLineTime] {
        lineTimes
            .map { UserLineTime(lineKey: $0.key, offsetMs: $0.value) }
            .sorted { $0.offsetMs < $1.offsetMs }
    }

    var isEmpty: Bool { text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
}

enum PendingMeetingNotes {
    /// `<Application Support>/meeting-notes` inside the app's container.
    ///
    /// Beside `pending/` (the kept recordings) and for the same reason: the
    /// temporary directory is reclaimed whenever the system feels like it,
    /// and the whole point of writing this down is that it is still there
    /// after a crash.
    static var directory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first ?? FileManager.default.temporaryDirectory
        return base.appending(path: "meeting-notes", directoryHint: .isDirectory)
    }

    /// On iOS, written with the same protection class as the kept
    /// recordings: unreadable on a device that has not been unlocked since
    /// boot, but readable while the screen is locked — a sync can still be
    /// running then. macOS has no equivalent; FileVault is the boundary.
    static var protection: [FileAttributeKey: Any] {
        #if os(iOS)
        [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
        #else
        [:]
        #endif
    }

    /// Save (or replace) one capture's notes. Called on every change, so it
    /// is an atomic overwrite of one small file, not an append log.
    static func save(_ note: PendingMeetingNote, in directory: URL = PendingMeetingNotes.directory) {
        var note = note
        note.updatedAt = Date()
        guard let data = try? JSONEncoder.pending.encode(note) else { return }
        let fm = FileManager.default
        try? fm.createDirectory(at: directory, withIntermediateDirectories: true,
                                attributes: protection)
        let url = file(for: note.clientCaptureId, in: directory)
        // `.atomic` so a crash mid-write leaves the previous version, never
        // a half-written one.
        try? data.write(to: url, options: .atomic)
        try? fm.setAttributes(protection, ofItemAtPath: url.path)
    }

    static func file(for clientCaptureId: String, in directory: URL = PendingMeetingNotes.directory) -> URL {
        directory.appending(path: clientCaptureId).appendingPathExtension("json")
    }

    static func load(_ clientCaptureId: String,
                     in directory: URL = PendingMeetingNotes.directory) -> PendingMeetingNote? {
        guard let data = try? Data(contentsOf: file(for: clientCaptureId, in: directory)) else { return nil }
        return try? JSONDecoder.pending.decode(PendingMeetingNote.self, from: data)
    }

    /// Everything waiting to sync, oldest first — the order it should go in,
    /// so the earliest meeting is the first one recovered.
    static func all(in directory: URL = PendingMeetingNotes.directory) -> [PendingMeetingNote] {
        let fm = FileManager.default
        guard let entries = try? fm.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
        else { return [] }
        return entries
            .filter { $0.pathExtension == "json" }
            .compactMap { url in
                guard let data = try? Data(contentsOf: url) else { return nil }
                return try? JSONDecoder.pending.decode(PendingMeetingNote.self, from: data)
            }
            .sorted { $0.startedAt < $1.startedAt }
    }

    /// The ones this identity typed. A shared device must not offer one
    /// person another's meeting.
    static func all(identityId: String,
                    in directory: URL = PendingMeetingNotes.directory) -> [PendingMeetingNote] {
        all(in: directory).filter { $0.identityId == identityId }
    }

    static func remove(_ clientCaptureId: String, in directory: URL = PendingMeetingNotes.directory) {
        try? FileManager.default.removeItem(at: file(for: clientCaptureId, in: directory))
    }

    /// Sign-out: the typing goes with the session. It was already synced
    /// or it never will be, and either way it is not the next person's.
    static func clearAll(in directory: URL = PendingMeetingNotes.directory) {
        try? FileManager.default.removeItem(at: directory)
    }

    // MARK: - Merging

    /// The divider a merge writes between the two devices' lines.
    static let divider = "---"

    /// Fold local typing into what the server already has.
    ///
    /// APPEND under a divider, never overwrite. Two devices typing the same
    /// meeting is two people's worth of attention on it, and silently
    /// dropping one of them is the one failure this feature cannot have.
    /// Lines the server already holds are skipped, so a reconnect does not
    /// duplicate what it already sent.
    static func merge(remote: String, local: String) -> String {
        let localTrimmed = local.trimmingCharacters(in: .whitespacesAndNewlines)
        let remoteTrimmed = remote.trimmingCharacters(in: .whitespacesAndNewlines)
        if localTrimmed.isEmpty { return remote }
        if remoteTrimmed.isEmpty { return local }
        if remote == local { return remote }
        let have = Set(lines(of: remote).map(normalise))
        let fresh = lines(of: local).filter { !have.contains(normalise($0)) }
        guard !fresh.isEmpty else { return remote }
        let base = remote.replacingOccurrences(of: "\\s+$", with: "", options: .regularExpression)
        return "\(base)\n\n\(divider)\n\(fresh.joined(separator: "\n"))"
    }

    static func lines(of text: String) -> [String] {
        text.split(separator: "\n", omittingEmptySubsequences: false)
            .map(String.init)
            .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
    }

    /// A line's identity for merging — the same rule the server keys by
    /// (`action_items.normalise_text` over the line without its bullet), so
    /// "- Ask about budget" and "ask about budget." are one line.
    static func normalise(_ line: String) -> String {
        let withoutBullet = line.replacingOccurrences(
            of: "^[\\s\\-•*·▪◦]*(?:\\d{1,2}[.)]\\s*)?[\\s\\-•*·]*",
            with: "", options: .regularExpression)
        return withoutBullet
            .replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespaces)
            .replacingOccurrences(of: "[.;,]+$", with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespaces)
            .lowercased()
    }
}
