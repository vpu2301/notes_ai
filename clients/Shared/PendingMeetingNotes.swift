import Foundation

/// What the author typed during a meeting, before the server had it. Written to disk on every change (debounced), keyed by the capture, replayed when there is a network again.
struct PendingMeetingNote: Codable, Equatable, Sendable {
    /// The capture's idempotency key; also the file name, so two devices never collide.
    var clientCaptureId: String
    /// The note, once the server opened one. Nil = still to be created (offline, or `startMeeting` failed).
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
    /// The invite's people and agenda, so an offline capture still opens with them.
    var calendar: MeetingCalendarContext?
    /// Who was signed in, and where it goes; a shared device must not sync one person's meeting into another's workspace.
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
    /// `<Application Support>/meeting-notes`, beside `pending/` and for the same reason: the temporary directory is reclaimed.
    static var directory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first ?? FileManager.default.temporaryDirectory
        return base.appending(path: "meeting-notes", directoryHint: .isDirectory)
    }

    /// On iOS, the same protection class as kept recordings (readable while locked, not before first unlock). macOS has no equivalent.
    static var protection: [FileAttributeKey: Any] {
        #if os(iOS)
        [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
        #else
        [:]
        #endif
    }

    /// Save (or replace) one capture's notes: an atomic overwrite of one small file.
    static func save(_ note: PendingMeetingNote, in directory: URL = PendingMeetingNotes.directory) {
        var note = note
        note.updatedAt = Date()
        guard let data = try? JSONEncoder.pending.encode(note) else { return }
        let fm = FileManager.default
        try? fm.createDirectory(at: directory, withIntermediateDirectories: true,
                                attributes: protection)
        let url = file(for: note.clientCaptureId, in: directory)
        // `.atomic` so a crash mid-write leaves the previous version.
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

    /// Everything waiting to sync, oldest first — the replay order.
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

    /// The ones this identity typed; a shared device must not offer another's.
    static func all(identityId: String,
                    in directory: URL = PendingMeetingNotes.directory) -> [PendingMeetingNote] {
        all(in: directory).filter { $0.identityId == identityId }
    }

    static func remove(_ clientCaptureId: String, in directory: URL = PendingMeetingNotes.directory) {
        try? FileManager.default.removeItem(at: file(for: clientCaptureId, in: directory))
    }

    /// Sign-out: the typing goes with the session.
    static func clearAll(in directory: URL = PendingMeetingNotes.directory) {
        try? FileManager.default.removeItem(at: directory)
    }

    // MARK: - Merging

    /// The divider a merge writes between the two devices' lines.
    static let divider = "---"

    /// Fold local typing into what the server has: APPEND under a divider, never
    /// overwrite. Lines the server already holds are skipped, so a reconnect does not duplicate.
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

    /// A line's identity for merging — the server's rule (`action_items.normalise_text` over the line without its bullet).
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
