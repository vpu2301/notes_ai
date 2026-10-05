import Foundation

/// A recording that was made but never uploaded: kept on disk with a sidecar, never destroyed by a failed request.
struct PendingCapture: Identifiable, Equatable, Sendable {
    var id: String { audioURL.lastPathComponent }
    let audioURL: URL
    let info: Info

    /// The sidecar beside the audio: everything the upload would carry, plus who was signed in.
    struct Info: Codable, Equatable, Sendable {
        var title: String
        var language: String
        var diarize: Bool
        var recordedAt: Date
        var identityId: String
        /// The workspace the recording was made for; the upload uses a token scoped to it.
        var tenantId: String?
        /// The "People" hint; nil from older sidecars.
        var speakersExpected: Int? = nil
        /// The capture context; nil from older sidecars. The source stays a
        /// string so an unknown value cannot make the recording unreadable.
        var speakersMax: Int? = nil
        var nameCandidates: [String]? = nil
        var captureSource: String? = nil
        /// When Record was pressed and how late audio reached the file; absent from older sidecars.
        var recordPressedAt: Date? = nil
        var firstFrameOffsetMs: Int? = nil

        enum CodingKeys: String, CodingKey {
            case title, language, diarize
            case recordedAt = "recorded_at"
            case identityId = "identity_id"
            case tenantId = "tenant_id"
            case speakersExpected = "speakers_expected"
            case speakersMax = "speakers_max"
            case nameCandidates = "name_candidates"
            case captureSource = "capture_source"
            case recordPressedAt = "record_pressed_at"
            case firstFrameOffsetMs = "first_frame_offset_ms"
        }

        /// The timing a retry sends: both halves, or nothing.
        var captureTiming: CaptureTiming? {
            get {
                guard let recordPressedAt, let firstFrameOffsetMs else { return nil }
                return CaptureTiming(recordPressedAt: recordPressedAt, firstFrameOffsetMs: firstFrameOffsetMs)
            }
            set {
                recordPressedAt = newValue?.recordPressedAt
                firstFrameOffsetMs = newValue?.firstFrameOffsetMs
            }
        }

        /// The context the upload carries; nil for a sidecar that has none.
        var captureContext: CaptureContext? {
            guard speakersMax != nil || nameCandidates != nil || captureSource != nil else { return nil }
            return CaptureContext(speakersMax: speakersMax, nameCandidates: nameCandidates ?? [],
                                  source: captureSource.flatMap(CaptureSource.init(rawValue:)) ?? .manual)
        }

        /// Write `context` into the sidecar fields.
        mutating func setCaptureContext(_ context: CaptureContext?) {
            speakersMax = context?.speakersMax
            nameCandidates = context.map(\.nameCandidates).flatMap { $0.isEmpty ? nil : $0 }
            captureSource = context?.source.rawValue
        }
    }
}

enum PendingCaptures {
    /// `<Application Support>/pending`: survives, unlike the temporary directory; left in the backup on purpose.
    static var directory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first ?? FileManager.default.temporaryDirectory
        return base.appending(path: "pending", directoryHint: .isDirectory)
    }

    /// Move the recording to `pending/` and write its sidecar. Audio first:
    /// a file without a sidecar is still recoverable. Nil if the move failed (original untouched).
    @discardableResult
    static func keep(_ fileURL: URL, info: PendingCapture.Info,
                     in directory: URL = PendingCaptures.directory) -> URL? {
        let fm = FileManager.default
        do {
            try fm.createDirectory(at: directory, withIntermediateDirectories: true,
                                   attributes: [.protectionKey: protection])
            let name = UUID().uuidString
            let destination = directory.appending(path: name)
                .appendingPathExtension(fileURL.pathExtension)
            try fm.moveItem(at: fileURL, to: destination)
            try? fm.setAttributes([.protectionKey: protection], ofItemAtPath: destination.path)
            write(info, beside: destination)
            return destination
        } catch {
            return nil
        }
    }

    /// Not `.complete`: an upload may still be running while the phone locks.
    /// `.completeUntilFirstUserAuthentication` still covers a stolen, never-unlocked handset.
    static let protection = FileProtectionType.completeUntilFirstUserAuthentication

    /// The sidecar for a kept recording.
    static func sidecar(of audioURL: URL) -> URL {
        audioURL.deletingPathExtension().appendingPathExtension("json")
    }

    static func write(_ info: PendingCapture.Info, beside audioURL: URL) {
        guard let data = try? JSONEncoder.pending.encode(info) else { return }
        let url = sidecar(of: audioURL)
        try? data.write(to: url)
        try? FileManager.default.setAttributes([.protectionKey: protection],
                                               ofItemAtPath: url.path)
    }

    /// Point a kept recording at another workspace. Never done automatically.
    @discardableResult
    static func retarget(_ capture: PendingCapture, to tenantId: String,
                         identityId: String? = nil) -> PendingCapture {
        var info = capture.info
        info.tenantId = tenantId
        if let identityId { info.identityId = identityId }
        write(info, beside: capture.audioURL)
        return PendingCapture(audioURL: capture.audioURL, info: info)
    }

    /// Whether this recording can be uploaded: only to the workspace it was
    /// made for, and only while the person still belongs to it (a note in a left workspace is a disclosure).
    static func needsWorkspace(_ capture: PendingCapture, memberships: [String]) -> Bool {
        guard let tenant = capture.info.tenantId, !tenant.isEmpty else {
            // No workspace recorded (older sidecar): the active workspace will do.
            return false
        }
        return !memberships.contains(tenant)
    }

    /// Delete a kept recording and its sidecar. The only path that destroys a recording; behind a confirmation.
    static func delete(_ capture: PendingCapture) {
        let fm = FileManager.default
        try? fm.removeItem(at: capture.audioURL)
        try? fm.removeItem(at: sidecar(of: capture.audioURL))
    }

    /// Every kept recording, newest first.
    static func all(in directory: URL = PendingCaptures.directory) -> [PendingCapture] {
        let fm = FileManager.default
        guard let entries = try? fm.contentsOfDirectory(at: directory,
                                                        includingPropertiesForKeys: nil) else {
            return []
        }
        return entries
            .filter { $0.pathExtension != "json" }
            .compactMap { audio in
                let sidecar = audio.deletingPathExtension().appendingPathExtension("json")
                guard let data = try? Data(contentsOf: sidecar),
                      let info = try? JSONDecoder.pending.decode(PendingCapture.Info.self, from: data)
                else { return nil }
                return PendingCapture(audioURL: audio, info: info)
            }
            .sorted { $0.info.recordedAt > $1.info.recordedAt }
    }

    /// How many recordings are waiting, without reading any of them.
    static func count(in directory: URL = PendingCaptures.directory) -> Int {
        let entries = (try? FileManager.default.contentsOfDirectory(at: directory,
                                                                    includingPropertiesForKeys: nil)) ?? []
        return entries.filter { $0.pathExtension != "json" }.count
    }

    /// The ones this identity made, newest first (a shared phone must not offer another's meeting).
    static func all(identityId: String,
                    in directory: URL = PendingCaptures.directory) -> [PendingCapture] {
        all(in: directory).filter { $0.info.identityId == identityId }
    }

    /// Kept for more than `days` by an identity no longer signed in here. Never swept.
    static func old(before days: Int = 30, excluding identityId: String,
                    in directory: URL = PendingCaptures.directory) -> [PendingCapture] {
        let cutoff = Date().addingTimeInterval(-Double(days) * 24 * 60 * 60)
        return all(in: directory).filter {
            $0.info.identityId != identityId && $0.info.recordedAt < cutoff
        }
    }
}

extension JSONEncoder {
    static let pending: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return encoder
    }()
}

extension JSONDecoder {
    static let pending: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }()
}
