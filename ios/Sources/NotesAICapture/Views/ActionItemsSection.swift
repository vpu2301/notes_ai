import SwiftUI

/// "Action items" above the sections (Sprint 20): one row per item with
/// owner / due chips and the response badges; tap for the responses.
struct ActionItemsSection: View {
    @ObservedObject var model: NoteViewModel
    @State private var expanded = true
    @State private var selected: ActionItem?

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Button {
                withAnimation(.easeInOut(duration: 0.15)) { expanded.toggle() }
            } label: {
                HStack(spacing: 8) {
                    Text("Action items")
                        .font(.dsDisplay(18, .semibold))
                        .foregroundStyle(DS.text1)
                    if model.liveDisputes > 0 {
                        Text("\(model.liveDisputes) disputed")
                            .font(.ds(10.5, .medium))
                            .foregroundStyle(DS.rec)
                    }
                    Spacer()
                    Image(systemName: expanded ? "chevron.down" : "chevron.right")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(DS.muted)
                }
            }
            .buttonStyle(.plain)
            if expanded {
                VStack(spacing: 0) {
                    ForEach(model.items) { item in
                        ActionItemRow(item: item) { selected = item }
                        if item.id != model.items.last?.id { DSDivider() }
                    }
                }
                .dsCard(padding: 0)
            }
        }
        .sheet(item: $selected) { item in
            ItemDetailSheet(model: model, itemId: item.id) { selected = nil }
                .presentationDetents([.medium, .large])
        }
    }
}

struct ActionItemRow: View {
    let item: ActionItem
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: item.status == .done ? "checkmark.square.fill" : item.status == .dropped ? "minus.square" : "square")
                    .foregroundStyle(item.status == .done ? DS.accent : DS.muted)
                    .padding(.top, 2)
                VStack(alignment: .leading, spacing: 4) {
                    Text(item.text)
                        .font(.dsBody)
                        .foregroundStyle(item.status == .dropped ? DS.muted : DS.text1)
                        .strikethrough(item.status == .dropped)
                        .multilineTextAlignment(.leading)
                    HStack(spacing: 6) {
                        if let owner = item.ownerLabel {
                            Text(item.ownerNeedsCheck ? "\(owner)?" : owner)
                                .font(.dsMeta).foregroundStyle(DS.muted)
                        }
                        if let due = item.dueDate ?? item.dueText {
                            Text(due).font(.dsMeta).foregroundStyle(DS.muted)
                        }
                        if item.counts.confirms > 0 {
                            Text("✓\(item.counts.confirms)").font(.dsMeta).foregroundStyle(DS.accent)
                        }
                        if item.counts.disputes > 0 {
                            Text("✗\(item.counts.disputes)").font(.dsMeta).foregroundStyle(DS.rec)
                        }
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(12)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// The responses on one item, each with the sender's label for the link
/// and the recipient's comment as plain text. "Mark done" and "Clear".
struct ItemDetailSheet: View {
    @ObservedObject var model: NoteViewModel
    let itemId: String
    let onClose: () -> Void

    private var item: ActionItem? { model.items.first { $0.id == itemId } }

    var body: some View {
        NavigationStack {
            ScrollView {
                if let item {
                    VStack(alignment: .leading, spacing: 16) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(item.text).font(.ds(17, .medium)).foregroundStyle(DS.text1)
                            HStack(spacing: 8) {
                                if let owner = item.ownerLabel {
                                    Text(item.ownerNeedsCheck ? "\(owner) · check owner" : owner)
                                        .font(.dsMeta).foregroundStyle(DS.muted)
                                }
                                if let due = item.dueDate ?? item.dueText {
                                    Text("due \(due)").font(.dsMeta).foregroundStyle(DS.muted)
                                }
                            }
                            Text(item.summary).font(.dsMeta).foregroundStyle(DS.muted)
                        }
                        .dsCard()
                        if !item.responses.isEmpty {
                            VStack(alignment: .leading, spacing: 10) {
                                DSLabel("Responses")
                                ForEach(item.responses) { response in
                                    VStack(alignment: .leading, spacing: 4) {
                                        HStack(spacing: 8) {
                                            Text(response.kind.rawValue.capitalized)
                                                .font(.ds(11, .semibold))
                                                .foregroundStyle(response.kind == .dispute ? DS.rec : DS.accent)
                                            Text(response.linkLabel.isEmpty ? "A recipient" : response.linkLabel)
                                                .font(.ds(13, .medium)).foregroundStyle(DS.text1)
                                            Spacer()
                                            Button("Clear") { Task { await model.clear(response) } }
                                                .font(.dsMeta)
                                        }
                                        if let comment = response.comment {
                                            // Recipient-authored: shown as text, nothing else.
                                            Text(verbatim: comment)
                                                .font(.dsBody).foregroundStyle(DS.text1)
                                                .textSelection(.enabled)
                                        }
                                    }
                                }
                            }
                            .dsCard()
                        }
                        if let error = model.actionError {
                            DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                        }
                    }
                    .padding(16)
                }
            }
            .background(DS.bg)
            .navigationTitle("Action item")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Close", action: onClose) }
                ToolbarItem(placement: .topBarTrailing) {
                    if let item {
                        Button(item.status == .done ? "Reopen" : "Mark done") { Task { await model.markDone(item) } }
                    }
                }
            }
        }
    }
}
