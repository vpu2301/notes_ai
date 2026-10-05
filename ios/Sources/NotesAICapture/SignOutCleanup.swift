import Foundation

/// Sprint 32 — what an explicit sign-out removes from this device besides
/// the session.
///
/// The kept recordings themselves stay: each is the one copy of a meeting,
/// and only the person may delete one (`PendingCaptures`). What goes is
/// what the account brought *to* them and what only makes sense while
/// signed in:
/// - the calendar invitees' names kept for the picklist (`name_candidates`,
///   Sprint 30) —
///   names of people, read from an account the sign-out has just
///   disconnected;
/// - the per-job "Looks right" answers on the speaker-count banner
///   (`speakerCountConfirmed.<job>`, Sprint 29), which list the account's
///   jobs;
/// - the scratchpads waiting to sync (`PendingMeetingNotes`, Sprint 34).
///   Unlike a recording, typed notes are not irreplaceable evidence of a
///   meeting that cannot happen again — they are the person's words about
///   their workspace, and they do not belong to whoever signs in next.
///
/// The rest of a sidecar — title, language, the People hint, the invitee
/// count cap, where the capture started, the channel layout — describes
/// the audio; an upload after the next sign-in needs it to come out as the
/// first attempt would have.
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

    /// Drop this identity's unsynced scratchpads. Another person's on a
    /// shared device are left alone, the same rule as the recordings.
    @discardableResult
    static func forgetMeetingNotes(identityId: String,
                                   in directory: URL = PendingMeetingNotes.directory) -> Int {
        guard !identityId.isEmpty else { return 0 }
        let mine = PendingMeetingNotes.all(identityId: identityId, in: directory)
        for note in mine { PendingMeetingNotes.remove(note.clientCaptureId, in: directory) }
        return mine.count
    }

    /// Drop the personal context from this identity's kept recordings.
    /// Other people's recordings on a shared device are not touched.
    /// Returns how many sidecars were rewritten.
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
