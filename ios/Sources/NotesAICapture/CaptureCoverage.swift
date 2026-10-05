import Foundation

// Sprint F1 — "from the first second". Kept identical in macos/ and ios/.
//
// Two halves: the capture side measures how long it took from the Record
// press to the first buffer written to the file and sends it with the
// upload; the transcript side shows which stretches of speech did not make
// it into the transcript, and why.

// MARK: - Capture timing (F1-1)

/// When Record was pressed and how long until audio first reached the file.
struct CaptureTiming: Codable, Equatable, Sendable {
    /// Wall clock at the Record press.
    var recordPressedAt: Date
    /// Milliseconds between the press and the first buffer written.
    var firstFrameOffsetMs: Int

    /// The server refuses anything outside this range.
    static let maxOffsetMs = 600_000

    init(recordPressedAt: Date, firstFrameOffsetMs: Int) {
        self.recordPressedAt = recordPressedAt
        self.firstFrameOffsetMs = Self.clamp(firstFrameOffsetMs)
    }

    /// Both moments known → the timing; either missing → nil (the upload
    /// then sends neither field).
    init?(pressedAt: Date?, firstFrameAt: Date?) {
        guard let pressedAt, let firstFrameAt else { return nil }
        self.init(recordPressedAt: pressedAt,
                  firstFrameOffsetMs: Self.offsetMs(pressedAt: pressedAt, firstFrameAt: firstFrameAt))
    }

    static func offsetMs(pressedAt: Date, firstFrameAt: Date) -> Int {
        clamp(Int((firstFrameAt.timeIntervalSince(pressedAt) * 1000).rounded()))
    }

    static func clamp(_ ms: Int) -> Int { min(maxOffsetMs, max(0, ms)) }

    /// `record_pressed_at` and `first_frame_offset_ms` for `POST /asr/jobs`.
    var formFields: [(String, String)] {
        [("record_pressed_at", Self.isoFormatter.string(from: recordPressedAt)),
         ("first_frame_offset_ms", String(firstFrameOffsetMs))]
    }

    /// A fresh formatter per call: it is not Sendable, and this runs once
    /// per upload.
    static var isoFormatter: ISO8601DateFormatter {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }

    /// Below this the start is not worth mentioning while recording.
    static let noticeableOffsetMs = 1_000

    /// "Recording from 0:03" — shown beside the counter when the audio
    /// started noticeably after the press; nil otherwise.
    static func latencyNotice(offsetMs: Int?) -> String? {
        guard let offsetMs, offsetMs >= noticeableOffsetMs else { return nil }
        let seconds = offsetMs / 1000
        return String(format: "Recording from %d:%02d", seconds / 60, seconds % 60)
    }
}

/// The moment the first buffer reached the file. Marked from the audio
/// thread, read from the main actor: a lock, and only the first mark counts.
final class FirstFrameClock: @unchecked Sendable {
    private let lock = NSLock()
    private var at: Date?
    private let now: @Sendable () -> Date

    init(now: @escaping @Sendable () -> Date = { Date() }) {
        self.now = now
    }

    func reset() {
        lock.lock()
        defer { lock.unlock() }
        at = nil
    }

    /// Called after every successful write; records only the first.
    func mark() {
        lock.lock()
        defer { lock.unlock() }
        if at == nil { at = now() }
    }

    var firstFrameAt: Date? {
        lock.lock()
        defer { lock.unlock() }
        return at
    }
}

// MARK: - Coverage on the result (F1-6)

/// `coverage` on `GET /asr/jobs/{id}/result`. Every field is optional so a
/// server that trims one never costs the transcript.
struct TranscriptCoverage: Decodable, Equatable, Sendable {
    var speechMs: Int? = nil
    var transcribedMs: Int? = nil
    var firstSpeechMs: Int? = nil
    var firstSegmentMs: Int? = nil
    var share: Double? = nil
    var vad: String? = nil
    var gaps: [CoverageGap]? = nil

    enum CodingKeys: String, CodingKey {
        case share, vad, gaps
        case speechMs = "speech_ms"
        case transcribedMs = "transcribed_ms"
        case firstSpeechMs = "first_speech_ms"
        case firstSegmentMs = "first_segment_ms"
    }
}

/// One stretch of speech that is not in the transcript.
struct CoverageGap: Decodable, Equatable, Sendable {
    var startMs: Int
    var endMs: Int
    /// no_audio | no_speech_detected | decoder_empty | prompt_echo |
    /// other_language | unknown — a string, so a new cause never breaks
    /// decoding.
    var cause: String

    enum CodingKeys: String, CodingKey {
        case cause
        case startMs = "start_ms"
        case endMs = "end_ms"
    }

    init(startMs: Int, endMs: Int, cause: String) {
        self.startMs = startMs
        self.endMs = endMs
        self.cause = cause
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        startMs = try c.decodeIfPresent(Int.self, forKey: .startMs) ?? 0
        endMs = try c.decodeIfPresent(Int.self, forKey: .endMs) ?? startMs
        cause = try c.decodeIfPresent(String.self, forKey: .cause) ?? "unknown"
    }

    /// Before the file started: there is nothing in the recording to open.
    var isSeekable: Bool { cause != "no_audio" }
}

/// `capture` on the result: what the recording app sent at upload.
struct CaptureInfo: Decodable, Equatable, Sendable {
    var recordPressedAt: String? = nil
    var firstFrameOffsetMs: Int? = nil

    enum CodingKeys: String, CodingKey {
        case recordPressedAt = "record_pressed_at"
        case firstFrameOffsetMs = "first_frame_offset_ms"
    }
}

/// "Not transcribed: 00:00–00:44 (audio started late)" — pure, so both
/// apps and the tests agree on the wording.
enum CoverageGapsFormatter {
    static let maxShown = 4

    struct Item: Equatable, Sendable {
        var text: String
        var startMs: Int
        var seekable: Bool
    }

    struct Line: Equatable, Sendable {
        var items: [Item]
        var more: Int

        var text: String {
            var out = "Not transcribed: " + items.map(\.text).joined(separator: ", ")
            if more > 0 { out += " +\(more) more" }
            return out
        }
    }

    /// Nil when nothing is missing — the view then shows nothing at all.
    static func line(_ coverage: TranscriptCoverage?) -> Line? {
        guard let gaps = coverage?.gaps, !gaps.isEmpty else { return nil }
        let items = gaps.prefix(maxShown).map { gap in
            Item(text: "\(time(gap.startMs))–\(time(gap.endMs)) (\(reason(gap.cause)))",
                 startMs: gap.startMs, seekable: gap.isSeekable)
        }
        return Line(items: Array(items), more: max(0, gaps.count - maxShown))
    }

    static func reason(_ cause: String) -> String {
        switch cause {
        case "no_audio": return "audio started late"
        case "no_speech_detected": return "no speech detected"
        case "other_language": return "another language"
        default: return "could not be decoded"
        }
    }

    /// "00:44", or "1:02:03" from an hour on.
    static func time(_ ms: Int) -> String {
        let total = max(0, ms) / 1000
        let h = total / 3600, m = (total % 3600) / 60, s = total % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, s) : String(format: "%02d:%02d", m, s)
    }
}
