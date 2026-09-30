import SwiftUI

/// "Still open from 12 Sep" — the previous meeting's unfinished business,
/// at the top of this one (Sprint 36).
///
/// The items keep the PREVIOUS note's key, so ticking one here does not
/// detach it from the meeting where it was agreed, or from the
/// recipient's confirmation on that meeting's shared page.
struct CarriedItemsView: View {
    @EnvironmentObject private var app: AppState
    @ObservedObject var model: NoteViewModel

    var body: some View {
        let items = model.carriedItems
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 8) {
                    Text("Still open from \(fromDate)")
                        .font(.dsDisplay(18, .semibold))
                        .foregroundStyle(DS.text1)
                    if let id = model.carried?.fromNoteId {
                        Button(model.carried?.fromNoteCode ?? "that meeting") { app.openNote(id) }
                            .buttonStyle(.plain)
                            .font(.dsMeta)
                            .foregroundStyle(DS.accentText)
                            .accessibilityHint("Opens the previous meeting's note")
                    }
                }
                VStack(spacing: 0) {
                    ForEach(items) { item in
                        row(item)
                        if item.id != items.last?.id { DSDivider() }
                    }
                }
                .dsCard(padding: 0)
            }
            .accessibilityElement(children: .contain)
            .accessibilityLabel("Still open from the last meeting")
        }
    }

    private var fromDate: String {
        guard let date = model.carried?.fromDate else { return "last time" }
        return date.formatted(.dateTime.day().month(.abbreviated))
    }

    private func row(_ item: CarriedItem) -> some View {
        let busy = model.carriedBusy == item.itemKey
        return VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top, spacing: 10) {
                Button {
                    Task { await model.setCarried(item, state: item.isDone ? "open" : "done_marked") }
                } label: {
                    Image(systemName: item.isDone ? "checkmark.square.fill" : "square")
                        .font(.dsSymbol(17, .regular))
                        .foregroundStyle(item.isDone ? DS.accent : DS.text3)
                        .frame(minWidth: 28, minHeight: 28)
                }
                .buttonStyle(.plain)
                .disabled(!model.editable || busy)
                .accessibilityLabel(item.text)
                .accessibilityValue(item.isDone ? "Done" : "Open")
                .accessibilityAddTraits(.isToggle)
                VStack(alignment: .leading, spacing: 3) {
                    Text(line(item))
                        .font(.dsBody)
                        .foregroundStyle(item.isDone ? DS.muted : DS.text1)
                        .strikethrough(item.isDone, color: DS.muted)
                        .fixedSize(horizontal: false, vertical: true)
                    // The recording said it was done, and these are the words.
                    if item.state == "done_mentioned", let quote = item.doneQuote, !quote.isEmpty {
                        Text((item.doneSpeaker.map { "\($0): " } ?? "") + "“\(quote)”")
                            .font(.dsMeta)
                            .foregroundStyle(DS.muted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 0)
                if model.editable {
                    Button("Drop") { Task { await model.setCarried(item, state: "dropped") } }
                        .buttonStyle(DSButtonStyle(kind: .ghost, size: 13, height: 28))
                        .disabled(busy)
                        .accessibilityLabel("Drop \(item.text)")
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
    }

    private func line(_ item: CarriedItem) -> AttributedString {
        var out = AttributedString()
        if let owner = item.ownerLabel, !owner.isEmpty {
            var lead = AttributedString("\(owner): ")
            lead.font = .ds(16, .semibold)
            out += lead
        }
        out += AttributedString(item.text)
        if let due = item.dueText, !due.isEmpty {
            var tail = AttributedString(" — \(due)")
            tail.foregroundColor = DS.muted
            out += tail
        }
        return out
    }
}
