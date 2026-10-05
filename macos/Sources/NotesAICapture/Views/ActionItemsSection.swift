import SwiftUI

/// "Action items" above the sections (Sprint 20): a disclosure with one
/// row per item; a click opens the responses in a popover.
struct ActionItemsSection: View {
    @ObservedObject var model: NoteViewModel
    @State private var expanded = true
    @State private var openItemId: String?

    var body: some View {
        DisclosureGroup(isExpanded: $expanded) {
            VStack(spacing: 0) {
                ForEach(model.items) { item in
                    ActionItemRow(item: item, open: openItemId == item.id) { openItemId = item.id }
                        .popover(isPresented: Binding(
                            get: { openItemId == item.id },
                            set: { if !$0 { openItemId = nil } }
                        ), arrowEdge: .bottom) {
                            ItemDetailPopover(model: model, itemId: item.id)
                        }
                    if item.id != model.items.last?.id { DSDivider() }
                }
            }
            .dsCard(padding: 0)
            .padding(.top, 6)
        } label: {
            HStack(spacing: 8) {
                Text("Action items")
                    .font(.dsDisplay(18, .semibold))
                    .foregroundStyle(DS.text1)
                if model.liveDisputes > 0 {
                    Text("\(model.liveDisputes) disputed")
                        .font(.ds(10.5, .medium))
                        .foregroundStyle(DS.dangerText)
                }
            }
        }
    }
}

struct ActionItemRow: View {
    let item: ActionItem
    let open: Bool
    let onTap: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: onTap) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: item.status == .done ? "checkmark.square.fill" : item.status == .dropped ? "minus.square" : "square")
                    .foregroundStyle(item.status == .done ? DS.accent : DS.muted)
                    .padding(.top, 2)
                VStack(alignment: .leading, spacing: 3) {
                    Text(item.text)
                        .font(.dsBody)
                        .foregroundStyle(item.status == .dropped ? DS.muted : DS.text1)
                        .strikethrough(item.status == .dropped)
                        .multilineTextAlignment(.leading)
                    HStack(spacing: 6) {
                        if let owner = item.ownerLabel {
                            Text(item.ownerNeedsCheck ? "\(owner)?" : owner)
                                .font(.dsMeta).foregroundStyle(DS.muted)
                                .help(item.ownerNeedsCheck ? "Owner inferred — check it" : "Owner")
                        }
                        if let due = item.dueDate ?? item.dueText {
                            Text(due).font(.dsMeta).foregroundStyle(DS.muted)
                        }
                        if item.counts.confirms > 0 {
                            Text("✓\(item.counts.confirms)").font(.dsMeta).foregroundStyle(DS.accent)
                        }
                        if item.counts.disputes > 0 {
                            Text("✗\(item.counts.disputes)").font(.dsMeta).foregroundStyle(DS.dangerText)
                        }
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(10)
            .background(hover || open ? DS.surface : .clear)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
    }
}

/// The responses on one item, each with the sender's label for the link
/// and the recipient's comment as plain text. "Mark done" and "Clear".
struct ItemDetailPopover: View {
    @ObservedObject var model: NoteViewModel
    let itemId: String

    private var item: ActionItem? { model.items.first { $0.id == itemId } }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let item {
                Text(item.text).font(.ds(14, .medium)).foregroundStyle(DS.text1)
                HStack(spacing: 8) {
                    if let owner = item.ownerLabel {
                        Text(item.ownerNeedsCheck ? "\(owner) · check owner" : owner)
                            .font(.dsMeta).foregroundStyle(DS.muted)
                    }
                    if let due = item.dueDate ?? item.dueText {
                        Text("due \(due)").font(.dsMeta).foregroundStyle(DS.muted)
                    }
                    Spacer()
                    Text(item.summary).font(.dsMeta).foregroundStyle(DS.muted)
                }
                if !item.responses.isEmpty {
                    DSDivider()
                    ForEach(item.responses) { response in
                        VStack(alignment: .leading, spacing: 3) {
                            HStack(spacing: 8) {
                                Text(response.kind.rawValue.capitalized)
                                    .font(.ds(11, .semibold))
                                    .foregroundStyle(response.kind == .dispute ? DS.dangerText : DS.accent)
                                Text(response.linkLabel.isEmpty ? "A recipient" : response.linkLabel)
                                    .font(.ds(12.5, .medium)).foregroundStyle(DS.text1)
                                Spacer()
                                Button("Clear") { Task { await model.clear(response) } }
                                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 11, height: 22))
                            }
                            if let comment = response.comment {
                                // Recipient-authored: shown as text, nothing else.
                                Text(verbatim: comment)
                                    .font(.ds(12.5)).foregroundStyle(DS.text1)
                                    .textSelection(.enabled)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                }
                if let error = model.actionError {
                    DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                }
                DSDivider()
                HStack {
                    Spacer()
                    Button(item.status == .done ? "Reopen" : "Mark done") { Task { await model.markDone(item) } }
                        .buttonStyle(DSButtonStyle(kind: .primary, height: 26))
                }
            }
        }
        .padding(14)
        .frame(width: 360)
    }
}
