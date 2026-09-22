import SwiftUI

/// "Remember John Mayer for this workspace?" — offered once, after the
/// author fixes a speaker's name (Sprint 35).
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
                    Text("Remember **\(offer.term)** for this workspace? We'll give the spelling to the transcriber before your next recording.")
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
            .accessibilityLabel("Remember \(offer.term) for this workspace")
        }
    }
}
