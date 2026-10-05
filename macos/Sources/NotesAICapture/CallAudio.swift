import AVFoundation
import Foundation

// Recording the call audio: the consent posture and the two upload fields that come with it.

/// The call-audio notice accepted before recording other participants. Stored with the version accepted; raising `currentVersion` asks again.
struct CallAudioConsent {
    static let currentVersion = 1
    static let versionKey = "callAudioConsentVersion"
    static let acceptedAtKey = "callAudioConsentAcceptedAt"

    /// The help page the notice and Settings link to (`Product.helpSite`).
    static let helpURL = Product.help("recording-call-audio")

    /// A sentence the person can say at the start of a call.
    static let suggestedSentence =
        "Before we start: I'm recording this call with Notes AI so I can take notes. Is everyone OK with that?"

    /// Deep link to Privacy & Security → Screen & System Audio Recording. `Privacy_ScreenCapture`
    /// is that pane's anchor since macOS 13; there is no separate public anchor for audio-only.
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

/// `channel_layout` for the upload: `mic_system` only when the file really has two channels; declaring a layout the file lacks is a 422.
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

/// `local_speaker_name`: the account owner's display name, whitespace collapsed, ≤ 80 chars; nil when empty. Personal data — never log it.
enum LocalSpeakerName {
    static let maxLength = 80

    static func normalized(_ name: String?) -> String? {
        guard let name else { return nil }
        let collapsed = name.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard !collapsed.isEmpty else { return nil }
        return String(collapsed.prefix(maxLength))
    }
}

/// The capture card's one line about what is being recorded.
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
