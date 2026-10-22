import Foundation
import SwiftUI

/// Client events for pipeline telemetry (telemetry sprint 3): what the user saw, and when.
/// Events, times and counts only — never transcript or note content. Fail-open: the UI never
/// waits on it; a failed send is kept on disk, retried with backoff and dropped after 24 h.
enum ClientEventName: String, Codable, Sendable {
    case recordingStopped = "recording_stopped"
    case importSubmitted = "import_submitted"
    case uploadStarted = "upload_started"
    case uploadFinished = "upload_finished"
    case transcriptDisplayed = "transcript_displayed"
    case speakerLabelsDisplayed = "speaker_labels_displayed"
    case notesDisplayed = "notes_displayed"
    case errorShown = "error_shown"
}

struct QueuedClientEvent: Codable, Equatable, Sendable {
    let eventId: String
    var recordingId: String
    let client: String
    let clientVersion: String
    let event: ClientEventName
    let clientWallUtc: Date
    /// Only when the event is stamped as it happens (not for a time passed in later).
    let clientMonotonicNs: UInt64?
    let attributes: [String: Int]

    enum CodingKeys: String, CodingKey {
        case eventId = "event_id", recordingId = "recording_id", client
        case clientVersion = "client_version", event
        case clientWallUtc = "client_wall_utc", clientMonotonicNs = "client_monotonic_ns"
        case attributes
    }
}

actor TelemetryReporter {
    typealias Send = @Sendable (Data) async throws -> Void

    static let maxAge: TimeInterval = 24 * 60 * 60
    private static let maxQueue = 500

    private let client: String
    private let version: String
    private let send: Send
    private let file: URL?
    private let now: @Sendable () -> Date
    private var queue: [QueuedClientEvent]
    /// Events waiting for the server's recording id, by local capture (a pending upload keeps its own).
    private var beforeRecording: [String: [QueuedClientEvent]] = [:]
    /// Once per (recording, event) while the app runs; the server keeps the first anyway.
    private var reported: Set<String> = []
    private var backoff: TimeInterval = 2
    private var flushTask: Task<Void, Never>?
    /// A send is awaiting the server; actor reentrancy must not send the same batch twice.
    private var sending = false

    init(client: String, version: String, file: URL?, now: @escaping @Sendable () -> Date = { Date() },
         send: @escaping Send) {
        self.client = client
        self.version = version
        self.file = file
        self.now = now
        self.send = send
        self.queue = Self.load(file)
    }

    private static func load(_ file: URL?) -> [QueuedClientEvent] {
        guard let file, let data = try? Data(contentsOf: file) else { return [] }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return (try? decoder.decode([QueuedClientEvent].self, from: data)) ?? []
    }

    private func save() {
        guard let file else { return }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        try? FileManager.default.createDirectory(at: file.deletingLastPathComponent(),
                                                 withIntermediateDirectories: true)
        if let data = try? encoder.encode(queue) { try? data.write(to: file, options: .atomic) }
    }

    private func make(_ event: ClientEventName, recordingId: String, attributes: [String: Int],
                      at: Date? = nil) -> QueuedClientEvent {
        QueuedClientEvent(eventId: UUID().uuidString.lowercased(), recordingId: recordingId,
                          client: client, clientVersion: version, event: event,
                          clientWallUtc: at ?? now(),
                          clientMonotonicNs: at == nil ? DispatchTime.now().uptimeNanoseconds : nil,
                          attributes: attributes)
    }

    /// An event for a recording the server knows (`recordingId` = the ASR job id).
    func report(_ event: ClientEventName, recordingId: String, attributes: [String: Int] = [:]) {
        let key = "\(recordingId):\(event.rawValue)"
        guard !reported.contains(key) else { return }
        reported.insert(key)
        queue.append(make(event, recordingId: recordingId, attributes: attributes))
        if queue.count > Self.maxQueue { queue.removeFirst(queue.count - Self.maxQueue) }
        save()
        scheduleFlush(after: 1)
    }

    /// An event before the server has given the recording an id (Stop, an import, the upload's
    /// first byte), kept under the local capture's id.
    func reportBeforeRecording(_ event: ClientEventName, capture: String, attributes: [String: Int] = [:],
                               at: Date? = nil) {
        beforeRecording[capture, default: []].append(make(event, recordingId: "", attributes: attributes, at: at))
    }

    /// The server accepted this capture: tag its waiting events with the recording and send them.
    func attachRecording(_ recordingId: String, capture: String) {
        for var e in beforeRecording.removeValue(forKey: capture) ?? [] {
            let key = "\(recordingId):\(e.event.rawValue)"
            guard !reported.contains(key) else { continue }
            reported.insert(key)
            e.recordingId = recordingId
            queue.append(e)
        }
        save()
        scheduleFlush(after: 0)
    }

    private func scheduleFlush(after seconds: TimeInterval) {
        guard flushTask == nil else { return }
        flushTask = Task { [weak self] in
            if seconds > 0 { try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000)) }
            await self?.flushNow()
        }
    }

    /// Send what is queued; on failure keep it and back off (2 s → 5 min).
    func flushNow() async {
        flushTask = nil
        guard !sending else { return }
        sending = true
        defer { sending = false }
        let cutoff = now().addingTimeInterval(-Self.maxAge)
        queue.removeAll { $0.clientWallUtc < cutoff }
        guard !queue.isEmpty else { save(); return }
        let batch = Array(queue.prefix(100))
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        struct Body: Encodable { let sentAt: Date; let events: [QueuedClientEvent]
            enum CodingKeys: String, CodingKey { case sentAt = "sent_at", events } }
        do {
            let data = try encoder.encode(Body(sentAt: now(), events: batch))
            try await send(data)
            let sent = Set(batch.map(\.eventId))
            queue.removeAll { sent.contains($0.eventId) }
            backoff = 2
            save()
            if !queue.isEmpty { scheduleFlush(after: 0) }
        } catch {
            save()
            backoff = min(backoff * 2, 300)
            scheduleFlush(after: backoff)
        }
    }

    // Test seams.
    func queued() -> [QueuedClientEvent] { queue }
}

/// Reports `event` once, after the view that shows it appeared with the data (`when` true).
struct ReportDisplayed: ViewModifier {
    let reporter: TelemetryReporter?
    let recordingId: String?
    let event: ClientEventName
    let when: Bool

    func body(content: Content) -> some View {
        content.task(id: when && recordingId != nil) {
            guard when, let reporter, let recordingId else { return }
            await reporter.report(event, recordingId: recordingId)
        }
    }
}

extension View {
    func reportDisplayed(_ reporter: TelemetryReporter?, recordingId: String?, event: ClientEventName,
                         when: Bool) -> some View {
        modifier(ReportDisplayed(reporter: reporter, recordingId: recordingId, event: event, when: when))
    }
}
