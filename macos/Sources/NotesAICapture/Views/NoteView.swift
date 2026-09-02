import AppKit
import SwiftUI

/// The note as a document, the way the web editor shows it: a slim bar
/// (status, save state, ⋯), the title, a meta line, Notes / Transcript
/// tabs, and one seamless text area per template section. Drafts autosave;
/// finalized notes are read-only here (amend and history stay in the web app).
struct NoteView: View {
    @EnvironmentObject private var app: AppState
    @StateObject private var model: NoteViewModel
    @State private var confirmFinalize = false
    @State private var confirmDelete = false
    @State private var sharePrompt = false
    @State private var shareEmail = ""
    @State private var shareNotMember: String?

    /// The capture this note came from, when it is one of this Mac's.
    private let capture: RecentCapture?

    init(capture: RecentCapture?, noteId: String, api: APIClient) {
        self.capture = capture
        _model = StateObject(wrappedValue: NoteViewModel(noteId: noteId, jobId: capture?.jobId, api: api))
    }

    var body: some View {
        VStack(spacing: 0) {
            bar
            DSDivider()
            if let error = model.loadError {
                failed(error)
            } else if model.isLoading || model.content == nil {
                loading
            } else {
                document
            }
        }
        .task(id: model.noteId) { await model.load() }
        .task(id: model.noteId) { await model.loadSharing() }
        .onChange(of: model.deleted) { _, deleted in
            // The note is gone; drop every local trace and go back home.
            if deleted { app.noteDeleted(model.noteId) }
        }
        .alert("Move this note to the trash?", isPresented: $confirmDelete) {
            Button("Move to Trash", role: .destructive) { Task { await model.delete() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("It disappears from everyone's list and any public link stops working. The note is kept for the workspace's records.")
        }
        .alert("Share with a colleague", isPresented: $sharePrompt) {
            TextField("name@company.com", text: $shareEmail)
            Button("Share") {
                let email = shareEmail.trimmingCharacters(in: .whitespaces)
                Task {
                    if await model.share(email: email) {
                        shareEmail = ""
                    } else if model.actionError == nil {
                        shareNotMember = email
                    }
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("They get a notification and an e-mail, and can read the note.")
        }
        .alert("Not in your workspace", isPresented: Binding(
            get: { shareNotMember != nil },
            set: { if !$0 { shareNotMember = nil } }
        )) {
            Button("Email a link") {
                let to = shareNotMember ?? ""
                shareNotMember = nil
                Task { await emailPublicLink(to: to) }
            }
            Button("Cancel", role: .cancel) { shareNotMember = nil }
        } message: {
            Text("\(shareNotMember ?? "That address") isn't a member here. You can e-mail them a public link instead.")
        }
        .alert("Finalize this note?", isPresented: $confirmFinalize) {
            Button("Finalize") { Task { await model.finalize() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Finalizing freezes the current version. You can still amend it later from the web app; every amendment is kept in the note's history.")
        }
        .alert("Something went wrong", isPresented: Binding(
            get: { model.actionError != nil },
            set: { if !$0 { model.actionError = nil } }
        )) {
            Button("OK") { model.actionError = nil }
        } message: {
            Text(model.actionError ?? "")
        }
    }

    // MARK: - Bar

    private var bar: some View {
        HStack(spacing: 10) {
            if let note = model.note, note.status != .draft {
                DSChip(text: note.status.label, tint: note.status.tint, soft: note.status.soft)
            }
            if model.conflict {
                DSChip(text: "Out of date", tint: DS.warn, soft: DS.warnSoft)
            }
            Spacer()
            if model.isDraft {
                saveStatus
            }
            if model.busy {
                ProgressView().controlSize(.small)
            }
            DSMenu(width: 236, items: menuItems)
        }
        .padding(.horizontal, 16)
        .frame(height: DS.topbarHeight)
    }

    private var saveStatus: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(saveTint)
                .frame(width: 6, height: 6)
            Text(model.conflict ? "Out of date" : model.saveState.label)
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
        }
        .animation(.easeOut(duration: 0.15), value: model.saveState)
    }

    private var saveTint: Color {
        switch model.saveState {
        case .saved: return DS.ok
        case .dirty, .saving: return DS.warn
        case .error: return DS.rec
        }
    }

    /// Open the mail client with the public link (creating it first).
    private func emailPublicLink(to: String) async {
        guard let url = await model.publicLinkURL(webAppURL: app.settings.webAppURL) else { return }
        let title = model.content?.title ?? ""
        let subject = title.isEmpty ? "A note" : title
        var parts = URLComponents()
        parts.scheme = "mailto"
        parts.path = to
        parts.queryItems = [
            .init(name: "subject", value: subject),
            .init(name: "body", value: "Here is the note \"\(subject)\":\n\n\(url.absoluteString)\n"),
        ]
        if let mail = parts.url { NSWorkspace.shared.open(mail) }
    }

    private func menuItems() -> [DSMenuItem] {
        let canManage = model.sharing?.canManage ?? true
        let hasLink = model.sharing?.publicLink != nil
        var items: [DSMenuItem] = [
            .item("Open in web app", symbol: "safari", hint: "⌘⇧O") {
                app.openNoteInBrowser(model.noteId)
            },
            .item("Copy link", symbol: "link") {
                if let url = app.noteURL(model.noteId) { copy(url.absoluteString) }
            },
            .separator,
            .item("Visible to everyone in the workspace", symbol: "person.2",
                  disabled: model.busy || !canManage, checked: model.isWorkspaceVisible) {
                Task { await model.setWorkspaceVisible(!model.isWorkspaceVisible) }
            },
            .item(hasLink ? "Copy public link" : "Create public link", symbol: "globe",
                  disabled: model.busy || !canManage) {
                Task {
                    if let url = await model.publicLinkURL(webAppURL: app.settings.webAppURL) {
                        copy(url.absoluteString)
                    }
                }
            },
            .item("Email link…", symbol: "envelope", disabled: model.busy || !canManage) {
                Task { await emailPublicLink(to: "") }
            },
            .item("Share with a colleague…", symbol: "person.badge.plus",
                  disabled: model.busy || !canManage) {
                sharePrompt = true
            },
        ]
        if hasLink && canManage {
            items.append(.item("Turn off public link", symbol: "globe.badge.chevron.backward",
                               disabled: model.busy) {
                Task { await model.revokePublicLink() }
            })
        }
        items.append(.separator)
        items.append(.item("Download PDF", symbol: "arrow.down.doc", disabled: model.busy) {
            Task { await model.exportPDF() }
        })
        items.append(.item("Download Markdown", symbol: "doc.plaintext", disabled: model.busy) {
            model.exportMarkdown()
        })
        if model.note?.status == .draft {
            items.append(.separator)
            items.append(.item("Finalize note", symbol: "checkmark.seal", disabled: model.busy) {
                confirmFinalize = true
            })
        } else if model.note?.status == .finalized || model.note?.status == .amended {
            items.append(.separator)
            items.append(.item("Amend in web app…", symbol: "pencil.line") {
                app.openNoteInBrowser(model.noteId)
            })
            if model.note?.status == .finalized {
                items.append(.item("Revert to draft", symbol: "arrow.uturn.backward", disabled: model.busy) {
                    Task { await model.revertToDraft() }
                })
            }
        }
        if !app.spaces.isEmpty {
            items.append(.separator)
            let current = app.spaceOf[model.noteId]
            for space in app.spaces {
                items.append(.item("Move to \(space.name)", symbol: "folder", checked: current == space.id) {
                    app.file(noteId: model.noteId, in: current == space.id ? nil : space.id)
                })
            }
        }
        items.append(.separator)
        if let capture {
            items.append(.item("Copy job ID", symbol: "number") { copy(capture.jobId) })
        }
        if model.sharing?.canDelete ?? true {
            items.append(.item("Move to trash", symbol: "trash", danger: true, disabled: model.busy) {
                confirmDelete = true
            })
        }
        return items
    }

    // MARK: - Document

    private var document: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                TextField("Untitled note", text: Binding(
                    get: { model.content?.title ?? "" },
                    set: { model.setTitle($0) }
                ))
                .textFieldStyle(.plain)
                .font(.dsDoc)
                .foregroundStyle(DS.text1)
                .disabled(!model.editable)
                .padding(.bottom, 8)

                if let note = model.note {
                    HStack(spacing: 6) {
                        Text(formatDateTime(note.createdAt))
                        Text("·")
                        Text("Updated \(relativeTime(note.updatedAt))")
                        Text("·")
                        Text(note.code).font(.dsMono(11.5))
                    }
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .padding(.bottom, 18)
                }

                if model.conflict {
                    HStack(spacing: 10) {
                        DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill",
                                 text: "Someone else saved a newer version of this note.")
                        Button("Reload latest") { Task { await model.load() } }
                            .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
                    }
                    .padding(.bottom, 16)
                }

                if capture?.status == .complete {
                    DSSegmentedPill(
                        options: [
                            .init(NoteViewModel.Tab.notes, label: "Notes"),
                            .init(NoteViewModel.Tab.transcript, label: "Transcript"),
                        ],
                        selection: $model.tab, height: 28)
                    .padding(.bottom, 20)
                }

                switch model.tab {
                case .notes: sections
                case .transcript: transcript
                }
            }
            .frame(maxWidth: 680, alignment: .leading)
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 40)
            .padding(.top, 28)
            .padding(.bottom, 60)
        }
    }

    private var sections: some View {
        VStack(alignment: .leading, spacing: 16) {
            if model.sections.isEmpty {
                Text("This note's template has no sections.")
                    .font(.dsBody)
                    .foregroundStyle(DS.muted)
            }
            ForEach(model.sections) { def in
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 8) {
                        Text(def.name)
                            .font(.dsDisplay(15, .medium))
                            .foregroundStyle(DS.text1)
                        if def.required == true {
                            Text("required")
                                .font(.ds(10, .medium))
                                .foregroundStyle(DS.muted)
                                .padding(.horizontal, 5)
                                .padding(.vertical, 1)
                                .background(Capsule().fill(DS.surface2))
                        }
                    }
                    if def.isFreeText {
                        SectionEditor(
                            text: Binding(
                                get: { model.content?.section(def.id).text ?? "" },
                                set: { model.setSectionText(def.id, $0) }
                            ),
                            placeholder: def.minChars.map { "At least \($0) characters…" } ?? "Start writing…",
                            editable: model.editable)
                    } else {
                        // Structured fields (choice, date, number) are edited in
                        // the web app; show the value read-only here.
                        let text = model.content?.section(def.id).text ?? ""
                        Text(text.isEmpty ? "Nothing entered." : text)
                            .font(.dsBody)
                            .foregroundStyle(text.isEmpty ? DS.muted : DS.text1)
                            .textSelection(.enabled)
                    }
                }
            }
        }
    }

    // MARK: - Transcript

    @ViewBuilder
    private var transcript: some View {
        VStack(alignment: .leading, spacing: 18) {
            if let error = model.transcriptError {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
            } else if let turns = model.turns {
                HStack {
                    Text(turns.isEmpty ? "Nothing was said." : speakerSummary(turns))
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                    Spacer()
                    Button {
                        copy(model.transcriptText())
                    } label: {
                        Label("Copy", systemImage: "doc.on.doc")
                    }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 26))
                    .disabled(turns.isEmpty)
                }
                ForEach(turns) { turn in
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 8) {
                            if let speaker = turn.speaker {
                                Text(speaker)
                                    .font(.dsDisplay(13.5, .medium))
                                    .foregroundStyle(DS.accentText)
                            }
                            Text(formatElapsed(ms: turn.startMs))
                                .font(.dsMono(11))
                                .foregroundStyle(DS.muted)
                        }
                        Text(turn.text)
                            .font(.dsBody)
                            .foregroundStyle(DS.text1)
                            .lineSpacing(3)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            } else {
                DSSkeleton(height: 56)
                DSSkeleton(height: 56)
                DSSkeleton(height: 56)
            }
        }
        .task { await model.loadTranscript() }
    }

    private func speakerSummary(_ turns: [TranscriptTurn]) -> String {
        let count = Set(turns.compactMap(\.speaker)).count
        return count <= 1 ? "1 speaker" : "\(count) speakers"
    }

    // MARK: - States

    private var loading: some View {
        VStack(alignment: .leading, spacing: 12) {
            DSSkeleton(height: 30, width: 280)
            DSSkeleton(height: 14, width: 200)
            Spacer().frame(height: 12)
            DSSkeleton(height: 72)
            DSSkeleton(height: 72)
            Spacer()
        }
        .frame(maxWidth: 680, alignment: .leading)
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 40)
        .padding(.top, 28)
    }

    private func failed(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: message)
            HStack {
                Button("Try again") { Task { await model.load() } }
                    .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                Button("Open in web app") { app.openNoteInBrowser(model.noteId) }
                    .buttonStyle(DSButtonStyle(kind: .ghost, height: 28))
            }
            Spacer()
        }
        .frame(maxWidth: 680, alignment: .leading)
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 40)
        .padding(.top, 28)
    }

    private func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }
}

/// A seamless, auto-growing text area (`.textarea.seamless`): no chrome
/// until it is hovered or focused, then a faint surface behind it.
private struct SectionEditor: View {
    @Binding var text: String
    let placeholder: String
    let editable: Bool

    @FocusState private var focused: Bool
    @State private var hover = false

    var body: some View {
        ZStack(alignment: .topLeading) {
            // TextEditor's intrinsic height counts newlines, not wrapped
            // lines; an invisible Text with the same metrics sets the real
            // height and the editor fills it.
            Text(text.isEmpty ? " " : text + " ")
                .font(.dsBody)
                .lineSpacing(3)
                .padding(.horizontal, 5)
                .padding(.vertical, 8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .opacity(0)
                .accessibilityHidden(true)
            if text.isEmpty {
                Text(editable ? placeholder : "Nothing entered.")
                    .font(.dsBody)
                    .foregroundStyle(DS.muted)
                    .padding(.horizontal, 5)
                    .padding(.vertical, 8)
                    .allowsHitTesting(false)
            }
            TextEditor(text: $text)
                .font(.dsBody)
                .foregroundStyle(DS.text1)
                .lineSpacing(3)
                .scrollContentBackground(.hidden)
                .scrollDisabled(true)
                .focused($focused)
                .disabled(!editable)
                .padding(.vertical, 4)
        }
        .frame(minHeight: 36)
        .padding(.horizontal, 6)
        .background(
            RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                .fill(focused ? DS.surface : (hover && editable ? DS.surfaceHover : .clear))
        )
        .overlay(
            RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                .strokeBorder(focused ? DS.text3.opacity(0.6) : (hover && editable ? DS.line : .clear), lineWidth: focused ? 1 : DS.hairline)
        )
        .padding(.horizontal, -6)
        .onHover { hover = $0 }
        .animation(.easeOut(duration: 0.12), value: focused)
        .animation(.easeOut(duration: 0.12), value: hover)
    }
}
