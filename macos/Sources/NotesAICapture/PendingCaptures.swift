import Foundation

/// A recording that was made but never uploaded.
///
/// Before IDX-M1 the pipeline deleted the file on **every** exit — including
/// the one where the upload failed because the session had ended. The
/// meeting was over, the audio was gone, and the app's only trace of it was
/// a red banner. Nothing about a failed request justifies destroying the
/// one copy of something that cannot be recorded again, so a recording that
/// did not reach the server is moved here instead and kept.
///
/// IDX-M2 adds the screen that retries these; until then they are files on
/// disk with a sidecar that says what they were, which is the part that
/// must not wait.
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

    /// The sidecar written beside the audio. Everything the upload would
    /// have carried, plus who was signed in when it was recorded — a Mac
    /// two people share should not offer one of them the other's meeting.
    struct Info: Codable, Equatable, Sendable {
        var title: String
        var language: String
        var diarize: Bool
        var recordedAt: Date
        var identityId: String
        var tenantId: String?

        enum CodingKeys: String, CodingKey {
            case title, language, diarize
            case recordedAt = "recorded_at"
            case identityId = "identity_id"
            case tenantId = "tenant_id"
        }
    }
}

enum PendingCaptures {
    /// `~/Library/Application Support/Notes AI Capture/pending`.
    ///
    /// Application Support rather than the temporary directory the
    /// recorder writes to: the point of moving the file is that it
    /// survives, and macOS empties the other one.
    static var directory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first ?? FileManager.default.temporaryDirectory
        return base
            .appending(path: "Notes AI Capture", directoryHint: .isDirectory)
            .appending(path: "pending", directoryHint: .isDirectory)
    }

    /// Move the recording out of harm's way and write its sidecar.
    ///
    /// The audio is moved first: if the sidecar cannot be written, a file
    /// with no description is still a recoverable meeting, while a
    /// description with no file is nothing at all. Returns where the audio
    /// ended up, or nil if even the move failed — in which case the
    /// original is left exactly where it is, which is still not deleted.
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

    /// Every kept recording, newest first. (IDX-M2's list; used here by
    /// the tests and by the Advanced tab's "reveal in Finder".)
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

    /// Delete a kept recording and its sidecar.
    ///
    /// Only ever called from an explicit user action (IDX-M2's Delete, or
    /// removing an account's local data) and after the server has taken
    /// the audio. Nothing in the app deletes one on its own.
    static func remove(_ capture: PendingCapture) {
        let fm = FileManager.default
        try? fm.removeItem(at: capture.audioURL)
        try? fm.removeItem(at: capture.sidecarURL)
    }

    /// Copy the audio somewhere the person chose, keeping the original
    /// until they say otherwise.
    static func export(_ capture: PendingCapture, to destination: URL) throws {
        let fm = FileManager.default
        if fm.fileExists(atPath: destination.path) {
            try fm.removeItem(at: destination)
        }
        try fm.copyItem(at: capture.audioURL, to: destination)
    }

    /// Point a kept recording at another workspace.
    ///
    /// The one repair for "you are no longer a member of the workspace
    /// this was recorded in": the audio is the person's, the workspace it
    /// was meant for is not reachable, and the alternative is exporting a
    /// file no server will ever see.
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
