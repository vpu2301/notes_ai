import SwiftUI

/// "Send "John Mayer" to the transcriber for every recording in this
/// workspace?" — offered once, after the author fixes a speaker's name
/// (Sprint 35; Sprint I2 made the question say what "remember" does).
///
/// The offer is the design. A vocabulary that learned silently would, the
/// first time it learned something wrong, quietly misspell a customer's
/// name in every note afterwards with nobody able to say why. One term,
/// one question, an answer the person gives.
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
