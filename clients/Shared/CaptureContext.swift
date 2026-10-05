import Foundation

/// Where a capture started and what the calendar knew; travels with the recording
/// and goes out as optional form fields of `POST /asr/jobs`. The invitee count is
/// a CAP (`speakers_max`), never exact; `speakers_expected` wins on the server.
struct CaptureContext: Equatable, Sendable {
    /// `speakers_max`: min(invitees, 8), only for events with ≥ 2 invitees.
    var speakersMax: Int?
    /// `name_candidates`: invitees' names, the current user excluded, ≤ 12.
    var nameCandidates: [String]
    var source: CaptureSource
    /// How many were invited, for the capture card's quiet line. Not sent.
    var invited: Int = 0

    static let manual = CaptureContext(speakersMax: nil, nameCandidates: [], source: .manual)
    static let upload = CaptureContext(speakersMax: nil, nameCandidates: [], source: .upload)

    /// The server's caps (asr-service validates the same numbers).
    static let maxSpeakers = 8
    static let maxCandidates = 12
    static let maxNameLength = 80

    /// A capture started from a calendar event. `attendeeCount` includes the current
    /// user (below 2 there is no meeting to cap); `excluding` removes the current user from `names`.
    static func calendarEvent(attendeeCount: Int, names: [String],
                              excluding: [String] = []) -> CaptureContext {
        CaptureContext(
            speakersMax: attendeeCount >= 2 ? min(attendeeCount, maxSpeakers) : nil,
            nameCandidates: candidates(names, excluding: excluding),
            source: .calendarEvent,
            invited: max(attendeeCount, 0))
    }

    /// Names worth offering: whitespace collapsed, control chars out, 1…80 chars, no e-mail addresses, no duplicates, excluded ones out, ≤ 12.
    static func candidates(_ names: [String], excluding: [String] = []) -> [String] {
        let excluded = Set(excluding.map { $0.lowercased() })
        var seen = Set<String>()
        var out: [String] = []
        for raw in names {
            let visible = String(raw.unicodeScalars.filter { !CharacterSet.controlCharacters.contains($0) })
            let name = visible.split(whereSeparator: \.isWhitespace).joined(separator: " ")
            guard !name.isEmpty, name.count <= maxNameLength, !name.contains("@") else { continue }
            let key = name.lowercased()
            guard !excluded.contains(key), seen.insert(key).inserted else { continue }
            out.append(name)
            if out.count == maxCandidates { break }
        }
        return out
    }

    /// "3 invited · names will be offered for speakers"; nil when not started from a meeting with guests.
    var inviteLine: String? {
        guard source == .calendarEvent, invited >= 2 else { return nil }
        return nameCandidates.isEmpty
            ? "\(invited) invited"
            : "\(invited) invited · names will be offered for speakers"
    }

    /// The form fields this context adds. Hints only when speakers are told apart; the source always goes.
    func formFields(diarize: Bool) -> [(String, String)] {
        var fields: [(String, String)] = []
        if diarize, let speakersMax { fields.append(("speakers_max", String(speakersMax))) }
        if diarize, !nameCandidates.isEmpty, let json = Self.encodeNames(nameCandidates) {
            fields.append(("name_candidates", json))
        }
        fields.append(("capture_source", source.rawValue))
        return fields
    }

    /// `["Anna Keller","Tom Berg"]` — the JSON string form the server takes.
    static func encodeNames(_ names: [String]) -> String? {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.withoutEscapingSlashes]
        guard let data = try? encoder.encode(names) else { return nil }
        return String(decoding: data, as: UTF8.self)
    }

    /// The same capture without the names, for a second try after `name_candidates_invalid`.
    var withoutNames: CaptureContext {
        var copy = self
        copy.nameCandidates = []
        return copy
    }
}

/// `capture_source` on the upload.
enum CaptureSource: String, Codable, Sendable {
    case calendarEvent = "calendar_event"
    case manual
    case upload
}
