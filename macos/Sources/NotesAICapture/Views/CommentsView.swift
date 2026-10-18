import AppKit
import SwiftUI

/// The note's comments, grouped by what they were left on, with a compose box for commenters.
/// Bodies are plain text from other people: shown verbatim, never as markup.
struct CommentsView: View {
    @ObservedObject var collab: NoteCollaboration
    @ObservedObject var model: NoteViewModel
    let onClose: () -> Void

    @State private var editingId: String?
    @State private var editDraft = ""
    @FocusState private var composeFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            DSDivider()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if collab.groups.isEmpty {
                        Text(collab.loaded ? "No comments yet." : "Loading…")
                            .font(.dsBody)
                            .foregroundStyle(DS.muted)
                            .padding(.top, 8)
                    }
                    ForEach(collab.groups) { group in
                        VStack(alignment: .leading, spacing: 10) {
                            Text(group.removed ? "On a removed line" : anchorTitle(group.anchor))
                                .font(.ds(11.5, .semibold))
                                .foregroundStyle(group.removed ? DS.muted : DS.text3)
                                .lineLimit(2)
                            ForEach(group.comments) { comment in
                                commentRow(comment)
                            }
                        }
                    }
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            if model.canComment {
                DSDivider()
                compose
            }
        }
        .background(DS.bg)
        .onChange(of: collab.anchor) { _, _ in composeFocused = true }
    }

    private var header: some View {
        HStack(spacing: 8) {
            Text("Comments")
                .font(.dsDisplay(15, .medium))
                .foregroundStyle(DS.text1)
            if collab.openCount > 0 {
                Text("\(collab.openCount)").font(.ds(12.5)).foregroundStyle(DS.muted).monospacedDigit()
            }
            Spacer()
            if collab.resolvedCount > 0 {
                Button(collab.showResolved ? "Hide resolved" : "Show resolved (\(collab.resolvedCount))") {
                    collab.showResolved.toggle()
                }
                .buttonStyle(DSButtonStyle(kind: .ghost, size: 11.5, height: 24))
            }
            Button(action: onClose) {
                Image(systemName: "xmark").font(.dsIcon(11, .semibold))
            }
            .buttonStyle(DSIconButtonStyle(size: 24))
            .help("Close comments")
            .accessibilityLabel("Close comments")
        }
        .padding(.horizontal, 16)
        .frame(height: DS.topbarHeight)
    }

    private func anchorTitle(_ anchor: CommentAnchor) -> String {
        switch anchor.kind {
        case "section":
            return model.sections.first { $0.id == anchor.key }?.name ?? "A section"
        case "item":
            return model.items.first { $0.itemKey == anchor.key }?.text ?? "An action item"
        default:
            return "On the note"
        }
    }

    @ViewBuilder
    private func commentRow(_ comment: NoteComment) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 7) {
                DSAvatar(name: comment.author.displayName, size: 20, collaborator: true)
                Text(comment.author.displayName)
                    .font(.ds(12.5, .medium))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                Text(relativeTime(comment.createdAt) + (comment.editedAt == nil ? "" : " · edited"))
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .lineLimit(1)
                Spacer(minLength: 4)
                if collab.busyId == comment.id {
                    ProgressView().controlSize(.mini)
                } else if comment.canEdit || comment.canResolve || comment.canDelete {
                    DSMenu(width: 180, dim: true, items: { actions(comment) })
                }
            }
            if editingId == comment.id {
                TextField("Comment", text: $editDraft, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(1...8)
                HStack {
                    Spacer()
                    Button("Cancel") { editingId = nil }
                        .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 24))
                    Button("Save") {
                        Task { if await collab.edit(comment, body: editDraft) { editingId = nil } }
                    }
                    .buttonStyle(DSButtonStyle(kind: .primary, size: 12, height: 24))
                }
            } else {
                Text(verbatim: comment.body)
                    .font(.ds(13))
                    .foregroundStyle(comment.isResolved ? DS.muted : DS.text1)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if comment.isResolved {
                Text("Resolved" + (comment.resolvedByDisplay.map { " by \($0)" } ?? ""))
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: DS.radius, style: .continuous).fill(DS.surface))
        .overlay(RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
            .strokeBorder(DS.line, lineWidth: DS.hairline))
    }

    private func actions(_ comment: NoteComment) -> [DSMenuItem] {
        var items: [DSMenuItem] = []
        if comment.canEdit {
            items.append(.item("Edit", symbol: "pencil") {
                editDraft = comment.body
                editingId = comment.id
            })
        }
        if comment.canResolve {
            items.append(.item(comment.isResolved ? "Reopen" : "Resolve",
                               symbol: comment.isResolved ? "arrow.uturn.backward" : "checkmark") {
                Task { await collab.setResolved(comment, !comment.isResolved) }
            })
        }
        if comment.canDelete {
            items.append(.item("Delete", symbol: "trash", danger: true) {
                Task { await collab.delete(comment) }
            })
        }
        return items
    }

    // MARK: - Compose

    private var compose: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !collab.anchor.isNote {
                HStack(spacing: 6) {
                    Text("On: " + anchorTitle(collab.anchor))
                        .font(.dsMeta)
                        .foregroundStyle(DS.text3)
                        .lineLimit(1)
                    Button {
                        collab.anchor = .note
                    } label: {
                        Image(systemName: "xmark.circle.fill").font(.dsIcon(11))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(DS.muted)
                    .help("Comment on the whole note instead")
                }
            }
            if let unsent = collab.unsent {
                HStack(alignment: .top, spacing: 8) {
                    DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill",
                             text: "Not sent: \(collab.error ?? "no connection"). Your text is kept below.")
                    Button("Copy") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(unsent, forType: .string)
                    }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 24))
                }
            } else if let error = collab.error {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
            }
            TextField("Add a comment", text: $collab.draft, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(1...6)
                .focused($composeFocused)
                .disabled(collab.sending)
            HStack {
                if collab.sending {
                    ProgressView().controlSize(.mini)
                    Text("Sending…").font(.dsMeta).foregroundStyle(DS.muted)
                }
                Spacer()
                Button("Comment") { Task { await collab.send() } }
                    .buttonStyle(DSButtonStyle(kind: .primary, size: 12, height: 26))
                    .keyboardShortcut(.return, modifiers: .command)
                    .disabled(collab.sending
                              || collab.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(16)
    }
}

/// Who else has the note open: up to three initials, "Anna is viewing" on hover.
struct PresenceAvatars: View {
    let viewers: [PresenceViewer]

    var body: some View {
        if !viewers.isEmpty {
            HStack(spacing: -6) {
                ForEach(viewers.prefix(3)) { viewer in
                    DSAvatar(name: viewer.displayName, size: 22, collaborator: true)
                        .overlay(Circle().strokeBorder(DS.bg, lineWidth: 1.5))
                }
                if viewers.count > 3 {
                    Text("+\(viewers.count - 3)")
                        .font(.ds(10.5, .medium))
                        .foregroundStyle(DS.muted)
                        .padding(.leading, 10)
                }
            }
            .help(PresenceViewer.line(viewers))
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(PresenceViewer.line(viewers))
        }
    }
}
