import Foundation

/// Sprint 32 — what an explicit sign-out removes from this device besides
/// the session.
///
/// The kept recordings themselves stay: each is the one copy of a meeting,
/// and only the person may delete one (`PendingCaptures`). What goes is
/// what the account brought *to* them and what only makes sense while
/// signed in:
/// - the calendar invitees' names kept for the picklist (`name_candidates`,
///   Sprint 30) and the account's display name kept for the microphone
///   channel (`local_speaker_name`, Sprint 31) —
///   names of people, read from an account the sign-out has just
///   disconnected;
/// - the per-job "Looks right" answers on the speaker-count banner
///   (`speakerCountConfirmed.<job>`, Sprint 29), which list the account's
///   jobs.
///
/// The rest of a sidecar — title, language, the People hint, the invitee
/// count cap, where the capture started, the channel layout — describes
/// the audio; an upload after the next sign-in needs it to come out as the
/// first attempt would have.
enum SignOutCleanup {
    /// UserDefaults keys that belong to one job of the signed-in account.
    static let perJobKeyPrefixes = [NoteViewModel.countBannerKey("")]

    static func run(identityId: String, directory: URL = PendingCaptures.directory,
                    defaults: UserDefaults = .standard) {
        scrubPending(identityId: identityId, in: directory)
        forgetPerJobAnswers(in: defaults)
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
            guard let data = try? JSONEncoder.pending.encode(clean),
                  (try? data.write(to: capture.sidecarURL, options: .atomic)) != nil else { continue }
            changed += 1
        }
        return changed
    }

    /// The sidecar without the names the account brought to it.
    static func scrubbed(_ info: PendingCapture.Info) -> PendingCapture.Info {
        var copy = info
        copy.nameCandidates = nil
        copy.localSpeakerName = nil
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
