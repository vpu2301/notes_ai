import SwiftUI

/// Sprint 31 M-5 — shown the first time "Record call audio" is turned on
/// (and again whenever `CallAudioConsent.currentVersion` is raised). It
/// cannot be dismissed any other way than by answering: Accept turns the
/// setting on, Not now keeps recordings microphone-only.
struct CallAudioConsentSheet: View {
    @EnvironmentObject private var capture: CaptureViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                Image(systemName: "headphones")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(DS.accentText)
                Text("Record call audio?")
                    .font(.dsDisplay(18, .medium))
                    .foregroundStyle(DS.text1)
            }
            if CallAudioConsent().needsRenewal {
                DSNotice(tone: .info, symbol: "info.circle",
                         text: "This notice has changed since you last accepted it.")
            }
            VStack(alignment: .leading, spacing: 8) {
                bullet("Notes AI Capture will also record what this Mac plays during a recording — the voices of the other participants in your calls — not only your microphone.")
                bullet("You are responsible for telling the other participants that the call is recorded, and for getting their agreement where the law requires it.")
                bullet("macOS will ask you once to allow System Audio Recording for Notes AI Capture.")
            }
            VStack(alignment: .leading, spacing: 6) {
                Text("You could say:")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                Text("“\(CallAudioConsent.suggestedSentence)”")
                    .font(.ds(13))
                    .foregroundStyle(DS.text1)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: DS.radius).fill(DS.sidebar))
            }
            Link("About recording other participants", destination: CallAudioConsent.helpURL)
                .font(.dsMeta)
                .foregroundStyle(DS.accentText)
            HStack {
                Spacer()
                Button("Not now") { capture.declineCallAudioConsent() }
                    .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                    .keyboardShortcut(.cancelAction)
                Button("I'll inform participants — record call audio") { capture.acceptCallAudioConsent() }
                    .buttonStyle(DSButtonStyle(kind: .primary, height: 28))
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(22)
        .frame(width: 500)
        .background(DS.bg)
        .interactiveDismissDisabled()
    }

    private func bullet(_ text: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text("•").foregroundStyle(DS.muted)
            Text(text)
                .font(.ds(13))
                .foregroundStyle(DS.text1)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
