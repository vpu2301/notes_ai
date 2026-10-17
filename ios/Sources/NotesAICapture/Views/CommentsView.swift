import SwiftUI
import UIKit

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
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if collab.groups.isEmpty {
                        Text(collab.loaded ? "No comments yet." : "Loading…")
                            .font(.dsBody)
                            .foregroundStyle(DS.muted)
                    }
                    ForEach(collab.groups) { group in
                        VStack(alignment: .leading, spacing: 10) {
                            Text(group.removed ? "On a removed line" : anchorTitle(group.anchor))
                                .font(.ds(12.5, .semibold))
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
            .scrollDismissesKeyboard(.interactively)
            .background(DS.bg)
            .safeAreaInset(edge: .bottom, spacing: 0) {
                if model.canComment { compose }
            }
            .navigationTitle(collab.openCount > 0 ? "Comments (\(collab.openCount))" : "Comments")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Close", action: onClose) }
                if collab.resolvedCount > 0 {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button(collab.showResolved ? "Hide resolved" : "Resolved (\(collab.resolvedCount))") {
                            collab.showResolved.toggle()
                        }
                    }
                }
            }
        }
        .task {
            // Opened from a section or an item: straight to typing.
            if !collab.anchor.isNote { composeFocused = true }
        }
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
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                DSAvatar(name: comment.author.displayName, size: 24)
                Text(comment.author.displayName)
                    .font(.ds(14, .medium))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                Text(relativeTime(comment.createdAt) + (comment.editedAt == nil ? "" : " · edited"))
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .lineLimit(1)
                Spacer(minLength: 4)
                if collab.busyId == comment.id {
                    ProgressView().controlSize(.small)
                } else if comment.canEdit || comment.canResolve || comment.canDelete {
                    actions(comment)
                }
            }
            if editingId == comment.id {
                TextField("Comment", text: $editDraft, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(1...8)
                HStack {
                    Spacer()
                    Button("Cancel") { editingId = nil }
                    Button("Save") {
                        Task { if await collab.edit(comment, body: editDraft) { editingId = nil } }
                    }
                    .fontWeight(.semibold)
                }
                .font(.ds(14))
            } else {
                Text(verbatim: comment.body)
                    .font(.dsBody)
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
        .padding(12)
        .background(RoundedRectangle(cornerRadius: DS.radius, style: .continuous).fill(DS.surface))
        .overlay(RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
            .strokeBorder(DS.line, lineWidth: DS.hairline))
    }

    private func actions(_ comment: NoteComment) -> some View {
        Menu {
            if comment.canEdit {
                Button {
                    editDraft = comment.body
                    editingId = comment.id
                } label: { Label("Edit", systemImage: "pencil") }
            }
            if comment.canResolve {
                Button {
                    Task { await collab.setResolved(comment, !comment.isResolved) }
                } label: {
                    Label(comment.isResolved ? "Reopen" : "Resolve",
                          systemImage: comment.isResolved ? "arrow.uturn.backward" : "checkmark")
                }
            }
            if comment.canDelete {
                Button(role: .destructive) {
                    Task { await collab.delete(comment) }
                } label: { Label("Delete", systemImage: "trash") }
            }
        } label: {
            Image(systemName: "ellipsis")
                .font(.dsSymbol(14, .semibold))
                .foregroundStyle(DS.muted)
                .frame(width: 32, height: 28)
                .contentShape(Rectangle())
        }
        .accessibilityLabel("Comment actions")
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
                        Image(systemName: "xmark.circle.fill").font(.dsSymbol(13))
                    }
                    .foregroundStyle(DS.muted)
                    .accessibilityLabel("Comment on the whole note instead")
                }
            }
            if let unsent = collab.unsent {
                HStack(alignment: .top, spacing: 8) {
                    DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill",
                             text: "Not sent: \(collab.error ?? "no connection"). Your text is kept below.")
                    Button("Copy") { UIPasteboard.general.string = unsent }
                        .font(.ds(14, .medium))
                }
            } else if let error = collab.error {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
            }
            HStack(alignment: .bottom, spacing: 8) {
                TextField("Add a comment", text: $collab.draft, axis: .vertical)
                    .font(.dsBody)
                    .lineLimit(1...5)
                    .focused($composeFocused)
                    .disabled(collab.sending)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 9)
                    .background(RoundedRectangle(cornerRadius: DS.radius, style: .continuous).fill(DS.surface))
                    .overlay(RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                        .strokeBorder(DS.line, lineWidth: DS.hairline))
                if collab.sending {
                    ProgressView().frame(width: 38, height: 38)
                        .accessibilityLabel("Sending…")
                } else {
                    Button {
                        Task { await collab.send() }
                    } label: {
                        Image(systemName: "arrow.up")
                            .font(.dsSymbol(15, .semibold))
                            .frame(width: 38, height: 38)
                    }
                    .buttonStyle(DSButtonStyle(kind: .dark, size: 15, height: 38))
                    .disabled(collab.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .accessibilityLabel("Comment")
                }
            }
            if collab.sending {
                Text("Sending…").font(.dsMeta).foregroundStyle(DS.muted)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(DS.bg)
    }
}

/// Who else has the note open: up to three initials; VoiceOver reads "Anna is viewing".
struct PresenceAvatars: View {
    let viewers: [PresenceViewer]

    var body: some View {
        if !viewers.isEmpty {
            HStack(spacing: -7) {
                ForEach(viewers.prefix(3)) { viewer in
                    DSAvatar(name: viewer.displayName, size: 24)
                        .overlay(Circle().strokeBorder(DS.bg, lineWidth: 1.5))
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(PresenceViewer.line(viewers))
        }
    }
}
