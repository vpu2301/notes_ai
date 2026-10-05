import SwiftUI

/// "Send "John Mayer" to the transcriber for every recording in this workspace?" — offered once after a speaker's name is fixed. One term, one question; nothing learned silently.
struct RememberTermBanner: View {
    @ObservedObject var model: NoteViewModel

    var body: some View {
        if let offer = model.rememberOffer {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: "character.book.closed")
                        .font(.ds(14))
                        .foregroundStyle(DS.accentText)
                    Text("Send **\"\(offer.term)\"** to the transcriber for every recording in this workspace?")
                        .font(.dsMeta)
                        .foregroundStyle(DS.text2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                HStack(spacing: 8) {
                    Spacer()
                    Button("Not now") { model.dismissRememberOffer() }
                        .buttonStyle(DSButtonStyle(kind: .ghost, size: 13, height: 30))
                    Button("Remember") { Task { await model.acceptRememberOffer() } }
                        .buttonStyle(DSButtonStyle(kind: .primary, size: 13, height: 30))
                }
            }
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous)
                    .fill(DS.accentSoft)
            )
            .accessibilityElement(children: .contain)
            .accessibilityLabel("Send \(offer.term) to the transcriber for every recording in this workspace")
        }
    }
}
