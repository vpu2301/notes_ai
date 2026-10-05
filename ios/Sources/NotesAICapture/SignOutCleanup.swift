import Foundation

/// What an explicit sign-out removes besides the session: invitee names in
/// sidecars (`name_candidates`), per-job "Looks right" answers, and unsynced
/// scratchpads. The recordings and the rest of their sidecars stay.
enum SignOutCleanup {
    /// UserDefaults keys that belong to one job of the signed-in account.
    static let perJobKeyPrefixes = [NoteViewModel.countBannerKey("")]

    static func run(identityId: String, directory: URL = PendingCaptures.directory,
                    meetingNotes: URL = PendingMeetingNotes.directory,
                    defaults: UserDefaults = .standard) {
        scrubPending(identityId: identityId, in: directory)
        forgetMeetingNotes(identityId: identityId, in: meetingNotes)
        forgetPerJobAnswers(in: defaults)
    }

    /// Drop this identity's unsynced scratchpads; another person's are left alone.
    @discardableResult
    static func forgetMeetingNotes(identityId: String,
                                   in directory: URL = PendingMeetingNotes.directory) -> Int {
        guard !identityId.isEmpty else { return 0 }
        let mine = PendingMeetingNotes.all(identityId: identityId, in: directory)
        for note in mine { PendingMeetingNotes.remove(note.clientCaptureId, in: directory) }
        return mine.count
    }

    /// Drop the personal context from this identity's kept recordings. Returns how many sidecars were rewritten.
    @discardableResult
    static func scrubPending(identityId: String, in directory: URL = PendingCaptures.directory) -> Int {
        guard !identityId.isEmpty else { return 0 }
        var changed = 0
        for capture in PendingCaptures.all(in: directory) where capture.info.identityId == identityId {
            let clean = scrubbed(capture.info)
            guard clean != capture.info else { continue }
            PendingCaptures.write(clean, beside: capture.audioURL)
            changed += 1
        }
        return changed
    }

    /// The sidecar without the names the account brought to it.
    static func scrubbed(_ info: PendingCapture.Info) -> PendingCapture.Info {
        var copy = info
        copy.nameCandidates = nil
        return copy
    }

    /// Forget every per-job answer ("Looks right") given on this device.
    static func forgetPerJobAnswers(in defaults: UserDefaults = .standard) {
        for key in defaults.dictionaryRepresentation().keys
        where perJobKeyPrefixes.contains(where: { key.hasPrefix($0) }) {
            defaults.removeObject(forKey: key)
        }
    }
}
