import Foundation

/// A recording that was made but never uploaded.
///
/// Before IDX-I1 the pipeline deleted the file on **every** exit — including
/// the one where the upload failed because the session had ended. The
/// meeting was over, the audio was gone, and the app's only trace of it was
/// a red banner. Nothing about a failed request justifies destroying the
/// one copy of something that cannot be recorded again, so a recording that
/// did not reach the server is moved here instead and kept.
///
/// IDX-I2 adds the screen that retries these; until then they are files on
/// disk with a sidecar that says what they were, which is the part that
/// must not wait.
struct PendingCapture: Identifiable, Equatable, Sendable {
    var id: String { audioURL.lastPathComponent }
    let audioURL: URL
    let info: Info

    /// The sidecar written beside the audio. Everything the upload would
    /// have carried, plus who was signed in when it was recorded — a phone
    /// handed round a team should not offer one person another's meeting.
    struct Info: Codable, Equatable, Sendable {
        var title: String
        var language: String
        var diarize: Bool
        var recordedAt: Date
        var identityId: String
        /// The workspace the recording was made for. The upload is sent
        /// with a token scoped to it, not to whatever is active now.
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
    /// `<Application Support>/pending` inside the app's container.
    ///
    /// Application Support rather than the temporary directory the recorder
    /// writes to: the point of moving the file is that it survives, and iOS
    /// reclaims the other one whenever it feels like it. Application
    /// Support is also excluded from the iCloud backup of media by default
    /// only if marked; these are the user's own recordings, so they are
    /// left backed up.
    static var directory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first ?? FileManager.default.temporaryDirectory
        return base.appending(path: "pending", directoryHint: .isDirectory)
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

    /// The data-protection class these files are written with.
    ///
    /// Not `.complete`: an upload can still be running as the phone locks
    /// — the whole point of the `audio` background mode — and a file that
    /// becomes unreadable mid-read would fail the upload it was kept for.
    /// `.completeUntilFirstUserAuthentication` still means the recordings
    /// are unreadable on a phone that has not been unlocked since it was
    /// switched on, which is the threat a stolen handset actually poses.
    static let protection = FileProtectionType.completeUntilFirstUserAuthentication

    /// The sidecar for a kept recording.
    static func sidecar(of audioURL: URL) -> URL {
        audioURL.deletingPathExtension().appendingPathExtension("json")
    }

    private static func write(_ info: PendingCapture.Info, beside audioURL: URL) {
        guard let data = try? JSONEncoder.pending.encode(info) else { return }
        let url = sidecar(of: audioURL)
        try? data.write(to: url)
        try? FileManager.default.setAttributes([.protectionKey: protection],
                                               ofItemAtPath: url.path)
    }

    /// Point a kept recording at another workspace.
    ///
    /// The recording is the person's; the workspace they were in when
    /// they made it may be one they have since been removed from. Rather
    /// than lose the meeting, they can send it somewhere they still
    /// belong — which is a decision only they can make, so nothing here
    /// does it automatically.
    @discardableResult
    static func retarget(_ capture: PendingCapture, to tenantId: String,
                         identityId: String? = nil) -> PendingCapture {
        var info = capture.info
        info.tenantId = tenantId
        if let identityId { info.identityId = identityId }
        write(info, beside: capture.audioURL)
        return PendingCapture(audioURL: capture.audioURL, info: info)
    }

    /// Whether this recording can be uploaded at all.
    ///
    /// The rule, as a function of the two facts it depends on, so it can
    /// be exercised without a signed-in app: a recording goes to the
    /// workspace it was made for, and only if that workspace is still one
    /// the person belongs to. The client never uploads to a workspace it
    /// already knows it left — a note appearing in a workspace somebody
    /// was removed from is a disclosure, however it got there.
    static func needsWorkspace(_ capture: PendingCapture, memberships: [String]) -> Bool {
        guard let tenant = capture.info.tenantId, !tenant.isEmpty else {
            // Made before there was a workspace to record (or by a build
            // that did not write one): the active workspace will do.
            return false
        }
        return !memberships.contains(tenant)
    }

    /// Delete a kept recording and its sidecar.
    ///
    /// The only path in this app that destroys a recording, and it is
    /// reached from one place: a confirmation the person tapped through.
    static func delete(_ capture: PendingCapture) {
        let fm = FileManager.default
        try? fm.removeItem(at: capture.audioURL)
        try? fm.removeItem(at: sidecar(of: capture.audioURL))
    }

    /// Every kept recording, newest first. (IDX-I2's list; used here by the
    /// tests and by the Settings sheet's count.)
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

    /// The ones this identity made, newest first. A phone two people share
    /// must not offer one of them the other's meeting.
    static func all(identityId: String,
                    in directory: URL = PendingCaptures.directory) -> [PendingCapture] {
        all(in: directory).filter { $0.info.identityId == identityId }
    }

    /// Kept for more than `days` by an identity that is not signed in here
    /// any more. Listed under "Old recordings" so they can be exported or
    /// deleted deliberately — never swept.
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
