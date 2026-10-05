import Foundation

/// A recording that was made but never uploaded. Nothing about a failed request justifies destroying the one copy, so it is moved here and kept.
struct PendingCapture: Identifiable, Equatable, Sendable {
    var id: String { audioURL.lastPathComponent }
    let audioURL: URL
    let info: Info

    var sidecarURL: URL {
        audioURL.deletingPathExtension().appendingPathExtension("json")
    }

    /// How much audio this is, for the row that offers to send it.
    var byteCount: Int64 {
        let attributes = try? FileManager.default.attributesOfItem(atPath: audioURL.path)
        return (attributes?[.size] as? NSNumber)?.int64Value ?? 0
    }

    /// The sidecar beside the audio: everything the upload would have carried, plus who was signed in (a shared Mac must not offer another's meeting).
    struct Info: Codable, Equatable, Sendable {
        var title: String
        var language: String
        var diarize: Bool
        var recordedAt: Date
        var identityId: String
        var tenantId: String?
        /// The "People" hint, so a capture made offline still uploads with it. Nil from older sidecars.
        var speakersExpected: Int? = nil
        /// The capture context, so a kept meeting uploads with it. Nil from older sidecars. Source kept as a string so an unknown value never makes the recording unreadable.
        var speakersMax: Int? = nil
        var nameCandidates: [String]? = nil
        var captureSource: String? = nil
        /// `channel_layout` and `local_speaker_name` as recorded, so a retry uploads what the first attempt would have. Nil from older sidecars.
        var channelLayout: String? = nil
        var localSpeakerName: String? = nil
        /// When Record was pressed and how late audio reached the file. Nil from older sidecars and imported files.
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
            case channelLayout = "channel_layout"
            case localSpeakerName = "local_speaker_name"
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

        /// The `channel_layout` a retry sends: only while the file really has two channels (else a 422).
        func uploadChannelLayout(for audioURL: URL) -> String? {
            guard channelLayout != nil else { return nil }
            return ChannelLayout.field(forFileAt: audioURL)
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
    /// `~/Library/Application Support/Notes AI Capture/pending` — Application Support survives; macOS empties the temporary directory.
    static var directory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first ?? FileManager.default.temporaryDirectory
        return base
            .appending(path: "Notes AI Capture", directoryHint: .isDirectory)
            .appending(path: "pending", directoryHint: .isDirectory)
    }

    /// Move the recording out of harm's way and write its sidecar. Audio moved first: a
    /// file without a sidecar is still recoverable. Returns where it ended up, or nil
    /// if the move failed (the original is left where it is).
    @discardableResult
    static func keep(_ fileURL: URL, info: PendingCapture.Info,
                     in directory: URL = PendingCaptures.directory) -> URL? {
        let fm = FileManager.default
        do {
            try fm.createDirectory(at: directory, withIntermediateDirectories: true)
            let name = UUID().uuidString
            let destination = directory.appending(path: name)
                .appendingPathExtension(fileURL.pathExtension)
            try fm.moveItem(at: fileURL, to: destination)
            if let data = try? JSONEncoder.pending.encode(info) {
                try? data.write(to: destination.deletingPathExtension()
                    .appendingPathExtension("json"))
            }
            return destination
        } catch {
            return nil
        }
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

    /// Delete a kept recording and its sidecar. Only from an explicit user action or after the server took the audio.
    static func remove(_ capture: PendingCapture) {
        let fm = FileManager.default
        try? fm.removeItem(at: capture.audioURL)
        try? fm.removeItem(at: capture.sidecarURL)
    }

    /// Copy the audio somewhere the person chose, keeping the original.
    static func export(_ capture: PendingCapture, to destination: URL) throws {
        let fm = FileManager.default
        if fm.fileExists(atPath: destination.path) {
            try fm.removeItem(at: destination)
        }
        try fm.copyItem(at: capture.audioURL, to: destination)
    }

    /// Point a kept recording at another workspace — the repair for a lost membership.
    @discardableResult
    static func retarget(_ capture: PendingCapture, to tenantId: String) -> PendingCapture? {
        var info = capture.info
        info.tenantId = tenantId
        guard let data = try? JSONEncoder.pending.encode(info),
              (try? data.write(to: capture.sidecarURL)) != nil
        else { return nil }
        return PendingCapture(audioURL: capture.audioURL, info: info)
    }

    /// A name for the exported file: the meeting's title, plus its date.
    static func exportName(_ capture: PendingCapture) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HHmm"
        let stamp = formatter.string(from: capture.info.recordedAt)
        let title = capture.info.title
            .replacingOccurrences(of: "/", with: "-")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let base = title.isEmpty ? "Recording" : title
        return "\(base) \(stamp).\(capture.audioURL.pathExtension)"
    }

    /// How many recordings are waiting, without reading any of them.
    static func count(in directory: URL = PendingCaptures.directory) -> Int {
        let entries = (try? FileManager.default.contentsOfDirectory(at: directory,
                                                                    includingPropertiesForKeys: nil)) ?? []
        return entries.filter { $0.pathExtension != "json" }.count
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
