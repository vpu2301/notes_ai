import AVFoundation
import Foundation

// Sprint 31 — recording the call audio: the consent posture and the two
// upload fields that come with it.

/// The call-audio notice the person accepts before the app records other
/// participants. Stored on this Mac with the version accepted; raising
/// `currentVersion` (because the notice changed) asks again.
struct CallAudioConsent {
    static let currentVersion = 1
    static let versionKey = "callAudioConsentVersion"
    static let acceptedAtKey = "callAudioConsentAcceptedAt"

    /// The help page the notice and Settings link to. There is no public
    /// docs site in the repo yet; this is the address the page is expected
    /// at and must be published before release (see macos/README.md).
    static let helpURL = URL(string: "https://notes.ai/help/recording-call-audio")!

    /// A sentence the person can say at the start of a call.
    static let suggestedSentence =
        "Before we start: I'm recording this call with Notes AI so I can take notes. Is everyone OK with that?"

    /// Deep link to Privacy & Security → Screen & System Audio Recording,
    /// where the System Audio Recording permission lives. (`Privacy_ScreenCapture`
    /// is the anchor that pane has answered to since macOS 13; there is no
    /// separate public anchor for "System Audio Recording Only".)
    static let privacySettingsURL =
        URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!

    let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    /// The person accepted this version of the notice (or a later one).
    var isCurrent: Bool { defaults.integer(forKey: Self.versionKey) >= Self.currentVersion }

    /// They accepted some earlier version; the notice changed since.
    var needsRenewal: Bool {
        let accepted = defaults.integer(forKey: Self.versionKey)
        return accepted > 0 && accepted < Self.currentVersion
    }

    func accept(at date: Date = Date()) {
        defaults.set(Self.currentVersion, forKey: Self.versionKey)
        defaults.set(date, forKey: Self.acceptedAtKey)
    }
}

/// `channel_layout` for the upload (contract §1): `mic_system` only when
/// the file really has two channels (ch0 microphone, ch1 call audio);
/// nothing otherwise — the server's default is mono, and declaring a
/// layout the file does not have is a 422.
enum ChannelLayout {
    static let micSystem = "mic_system"

    static func field(channelCount: Int?) -> String? {
        channelCount == 2 ? micSystem : nil
    }

    /// The channel count of an audio file on disk, or nil if unreadable.
    static func channelCount(of url: URL) -> Int? {
        guard let file = try? AVAudioFile(forReading: url) else { return nil }
        return Int(file.fileFormat.channelCount)
    }

    static func field(forFileAt url: URL) -> String? {
        field(channelCount: channelCount(of: url))
    }
}

/// `local_speaker_name` (contract §1): the account owner's display name,
/// whitespace collapsed, at most 80 characters; nil when empty so the field
/// is omitted. It is personal data — never log it.
enum LocalSpeakerName {
    static let maxLength = 80

    static func normalized(_ name: String?) -> String? {
        guard let name else { return nil }
        let collapsed = name.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard !collapsed.isEmpty else { return nil }
        return String(collapsed.prefix(maxLength))
    }
}

/// The capture card's one line about what is being recorded (Sprint 31).
enum CaptureStateLine: Equatable {
    case micAndCall
    case callAudioLost
    /// Call audio was wanted; the tap could not start (permission off).
    case micOnlyPermissionOff
    case micOnlyConsentNeeded
    /// The setting is off (or this macOS cannot): today's line.
    case micOnly

    init(mode: CaptureMode, systemAudioLost: Bool) {
        switch mode {
        case .micAndSystem:
            self = systemAudioLost ? .callAudioLost : .micAndCall
        case .micOnly(let reason):
            switch reason {
            case .unavailable: self = .micOnlyPermissionOff
            case .consentNeeded: self = .micOnlyConsentNeeded
            case .settingOff, .unsupportedOS: self = .micOnly
            }
        }
    }
}
