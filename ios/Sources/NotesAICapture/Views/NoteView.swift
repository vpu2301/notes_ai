import SwiftUI
import UIKit

/// The note as a document, the way the web editor shows it: the title, a
/// meta line, Notes / Transcript tabs, and one seamless text area per
/// template section; status, save state and ⋯ live in the navigation bar.
/// Drafts autosave; finalized notes are read-only here (amend and history
/// stay in the web app).
struct NoteView: View {
    @EnvironmentObject private var app: AppState
    @StateObject private var model: NoteViewModel
    @State private var confirmFinalize = false
    @State private var confirmDelete = false
    @State private var shareByEmail = false
    /// Which speaker label is being renamed, and the text so far.
    @State private var editingSpeaker: String?
    @State private var speakerDraft = ""
    @State private var copied = false
    /// Which section is open in its editor. A draft reads as a document
    /// until you tap into one, and only one is ever open at a time.
    @State private var editingSection: String?
    /// What is typed in the ask bar at the foot of the note.
    @State private var askDraft = ""
    @FocusState private var askFocused: Bool

    /// The capture this note came from, when it is one of this phone's.
    private let capture: RecentCapture?

    init(capture: RecentCapture?, noteId: String, api: APIClient) {
        self.capture = capture
        _model = StateObject(wrappedValue: NoteViewModel(noteId: noteId, jobId: capture?.jobId, api: api))
    }

    var body: some View {
        Group {
            if let error = model.loadError {
                failed(error)
            } else if model.isLoading || model.content == nil {
                loading
            } else {
                document
            }
        }
        .background(DS.bg)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .principal) { barTitle }
            ToolbarItemGroup(placement: .topBarTrailing) {
                if model.busy {
                    ProgressView().controlSize(.small)
                }
                DSMenu(items: menuItems)
            }
        }
        .task(id: model.noteId) { await model.load() }
        .task(id: model.noteId) { await model.loadSharing() }
        .onDisappear { Task { await model.flush() } }
        .onChange(of: model.deleted) { _, deleted in
            // The note is gone; drop every local trace and go back home.
            if deleted { app.noteDeleted(model.noteId) }
        }
        .sheet(item: $model.shareItem) { item in
            ShareSheet(items: [item.url])
                .id(item.id)
                .presentationDetents([.medium, .large])
        }
        .alert("Move this note to the trash?", isPresented: $confirmDelete) {
            Button("Move to Trash", role: .destructive) { Task { await model.delete() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("It disappears from everyone's list and any public link stops working. The note is kept for the workspace's records.")
        }
        .sheet(isPresented: $shareByEmail) {
            ShareEmailSheet(
                noteTitle: model.content?.title ?? "",
                send: { recipients, message in
                    await model.sendShareEmail(recipients: recipients, message: message)
                },
                onClose: { shareByEmail = false })
        }
        .alert("Finalize this note?", isPresented: $confirmFinalize) {
            Button("Finalize") { Task { await model.finalize() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Finalizing freezes the current version. You can still amend it later from the web app; every amendment is kept in the note's history.")
        }
        .alert("Rename speaker", isPresented: Binding(
            get: { editingSpeaker != nil },
            set: { if !$0 { editingSpeaker = nil } }
        )) {
            TextField("Name", text: $speakerDraft)
            Button("Save") {
                if let label = editingSpeaker {
                    let name = speakerDraft
                    editingSpeaker = nil
                    Task { await model.renameSpeaker(label: label, to: name) }
                }
            }
            Button("Cancel", role: .cancel) { editingSpeaker = nil }
        } message: {
            Text(model.isDraft
                 ? "The name is used in the transcript and at the start of each turn in the note."
                 : "The name is used in the transcript; a finalized note keeps its text.")
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

    @ViewBuilder
    private var barTitle: some View {
        HStack(spacing: 8) {
            if let note = model.note, note.status != .draft {
                DSChip(text: note.status.label, tint: note.status.tint, soft: note.status.soft)
            }
            if model.conflict {
                DSChip(text: "Out of date", tint: DS.warn, soft: DS.warnSoft)
            } else if let label = model.oversightLabel {
                DSChip(text: label, tint: DS.info, soft: DS.infoSoft)
                    .accessibilityHint("You can see this note because you run this workspace. This view is recorded.")
            } else if model.isDraft {
                saveStatus
            }
        }
    }

    private var saveStatus: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(saveTint)
                .frame(width: 6, height: 6)
            Text(model.saveState.label)
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

    private func menuItems() -> [DSMenuItem] {
        let canManage = model.sharing?.canManage ?? true
        let hasLink = model.sharing?.publicLink != nil
        var items: [DSMenuItem] = [
            .item("Open in web app", symbol: "safari") {
                app.openNoteInBrowser(model.noteId)
            },
            .item("Copy link", symbol: "link") {
                if let url = app.noteURL(model.noteId) { copyToPasteboard(url.absoluteString) }
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
                        copyToPasteboard(url.absoluteString)
                    }
                }
            },
            // One entry, not two: whether a recipient is a colleague or
            // an outsider is the server's problem, not the sender's.
            .item("Send by email…", symbol: "envelope", disabled: model.busy || !canManage) {
                shareByEmail = true
            },
        ]
        if hasLink && canManage {
            items.append(.item("Turn off public link", symbol: "globe.badge.chevron.backward",
                               disabled: model.busy) {
                Task { await model.revokePublicLink() }
            })
        }
        items.append(.separator)
        items.append(.item("Share PDF", symbol: "arrow.down.doc", disabled: model.busy) {
            Task { await model.exportPDF() }
        })
        items.append(.item("Share Markdown", symbol: "doc.plaintext", disabled: model.busy) {
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
        if !model.chat.isEmpty {
            items.append(.separator)
            items.append(.item("Clear chat", symbol: "bubble.left.and.text.bubble.right") {
                model.clearChat()
            })
        }
        items.append(.separator)
        if let capture {
            items.append(.item("Copy job ID", symbol: "number") { copyToPasteboard(capture.jobId) })
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
        ScrollViewReader { proxy in
            ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                TextField("Untitled note", text: Binding(
                    get: { model.content?.title ?? "" },
                    set: { model.setTitle($0) }
                ), axis: .vertical)
                .textFieldStyle(.plain)
                .font(.dsDisplay(29))
                .foregroundStyle(DS.text1)
                .disabled(!model.editable)
                .padding(.bottom, 10)

                // The meta line is a row of pills, not a run of text: when
                // it was taken, what wrote it, where it is filed, what it
                // is called. Only the space is a control — the rest are the
                // facts you want at a glance. It scrolls sideways rather
                // than wrapping into three ragged rows on a narrow phone.
                if let note = model.note {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 7) {
                            DSMetaPill(symbol: "calendar", text: formatDateTime(note.createdAt))
                            DSMetaPill(text: "Updated \(relativeTime(note.updatedAt))")
                            if let template = model.templateName {
                                DSMetaPill(symbol: "sparkles", text: template, tone: .accent)
                            }
                            spacePill
                            DSMetaPill(text: note.code, mono: true)
                        }
                        .padding(.horizontal, DS.gutter)
                    }
                    .padding(.horizontal, -DS.gutter)
                    .padding(.bottom, 18)
                }

                if model.conflict {
                    VStack(alignment: .leading, spacing: 8) {
                        DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill",
                                 text: "Someone else saved a newer version of this note.")
                        Button("Reload latest") { Task { await model.load() } }
                            .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 34))
                    }
                    .padding(.bottom, 16)
                }

                if capture?.status == .complete {
                    DSSegmentedPill(
                        options: [
                            .init(NoteViewModel.Tab.notes, label: "Notes"),
                            .init(NoteViewModel.Tab.transcript, label: "Transcript"),
                        ],
                        selection: $model.tab, height: 36)
                    .padding(.bottom, 20)
                }

                switch model.tab {
                case .notes: sections
                case .transcript: transcript
                }

                if !model.chat.isEmpty || model.asking || model.askError != nil {
                    askThread.padding(.top, 32)
                }
                Color.clear.frame(height: 1).id("ask-end")
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, DS.gutter)
            .padding(.top, 12)
            // The composer is a bottom safe-area inset, so the scroll view
            // already keeps its height clear; this is just breathing room
            // under the last line.
            .padding(.bottom, 24)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: model.chat.count) { _, _ in
                withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo("ask-end", anchor: .bottom) }
            }
            .onChange(of: model.asking) { _, asking in
                if asking { withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo("ask-end", anchor: .bottom) } }
            }
        }
        // The composer sits over the document, under a short wash of the
        // page ground so a line of text never runs into it.
        .safeAreaInset(edge: .bottom, spacing: 0) { askBar }
    }

    // MARK: - Ask this note

    /// The thread: questions on the right in a quiet bubble, answers as a
    /// typeset document under a spark — one conversation about this note.
    private var askThread: some View {
        VStack(alignment: .leading, spacing: 16) {
            ForEach(model.chat) { message in
                switch message.role {
                case .user:
                    HStack {
                        Spacer(minLength: 48)
                        Text(message.text)
                            .font(.dsBody)
                            .foregroundStyle(DS.text1)
                            .textSelection(.enabled)
                            .padding(.horizontal, 13)
                            .padding(.vertical, 9)
                            .background(
                                RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous)
                                    .fill(DS.surface2)
                            )
                    }
                case .assistant:
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: "sparkles")
                            .font(.system(size: 14, weight: .medium))
                            .foregroundStyle(DS.accentText)
                            .frame(width: 20)
                        // An answer arrives as bullets and headings just as
                        // the note does, so it is typeset the same way.
                        RichTextView(text: message.text)
                    }
                }
            }
            if model.asking {
                HStack(spacing: 10) {
                    Image(systemName: "sparkles")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(DS.accentText)
                        .frame(width: 20)
                    Text("Thinking…")
                        .font(.dsBody)
                        .foregroundStyle(DS.muted)
                    ProgressView().controlSize(.small)
                }
            }
            if let error = model.askError {
                DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill", text: error)
            }
        }
    }

    /// The composer, floating over the foot of the document: one field,
    /// the send button lights up as soon as there is something to send.
    private var askBar: some View {
        HStack(spacing: 8) {
            Image(systemName: "sparkles")
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(DS.accentText)
            TextField("Ask about this note…", text: $askDraft, axis: .vertical)
                .textFieldStyle(.plain)
                .font(.ds(16))
                .foregroundStyle(DS.text1)
                .lineLimit(1...5)
                .focused($askFocused)
                .submitLabel(.send)
            Button {
                sendQuestion()
            } label: {
                Image(systemName: "arrow.up")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(DS.inkText)
                    .frame(width: 34, height: 34)
                    .background(Circle().fill(DS.ink))
            }
            .buttonStyle(.plain)
            .disabled(model.asking || askDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            .opacity(model.asking || askDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.3 : 1)
            .accessibilityLabel("Send")
        }
        .padding(.leading, 16)
        .padding(.trailing, 7)
        .padding(.vertical, 7)
        .background(
            RoundedRectangle(cornerRadius: DS.radiusXl, style: .continuous)
                .fill(DS.surface)
                .shadow(color: .black.opacity(0.14), radius: 18, y: 6)
        )
        .overlay(
            RoundedRectangle(cornerRadius: DS.radiusXl, style: .continuous)
                .strokeBorder(DS.line, lineWidth: DS.hairline)
        )
        .padding(.horizontal, DS.gutter)
        .padding(.bottom, 10)
        .padding(.top, 6)
        .background(
            LinearGradient(colors: [DS.bg.opacity(0), DS.bg], startPoint: .top, endPoint: .bottom)
                .allowsHitTesting(false)
        )
    }

    private func sendQuestion() {
        let question = askDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty, !model.asking else { return }
        askDraft = ""
        askFocused = false
        Task { await model.ask(question) }
    }

    private var sections: some View {
        VStack(alignment: .leading, spacing: 22) {
            if model.sections.isEmpty {
                Text("This note's template has no sections.")
                    .font(.dsBody)
                    .foregroundStyle(DS.muted)
            }
            ForEach(model.sections) { def in
                VStack(alignment: .leading, spacing: 7) {
                    HStack(spacing: 8) {
                        // No hanging "#" here — a phone has no gutter to
                        // hang it in, which is why the web drops it below
                        // 820px too.
                        Text(def.name)
                            .font(.dsDisplay(18, .semibold))
                            .foregroundStyle(DS.text1)
                        if def.required == true {
                            Text("required")
                                .font(.ds(10.5, .medium))
                                .foregroundStyle(DS.muted)
                                .padding(.horizontal, 5)
                                .padding(.vertical, 1)
                                .background(Capsule().fill(DS.surface2))
                        }
                    }
                    if def.isFreeText {
                        SectionField(
                            text: Binding(
                                get: { model.content?.section(def.id).text ?? "" },
                                set: { model.setSectionText(def.id, $0) }
                            ),
                            name: def.name,
                            placeholder: def.minChars.map { "At least \($0) characters…" } ?? "Start writing…",
                            editable: model.editable,
                            editing: Binding(
                                get: { editingSection == def.id },
                                set: { editingSection = $0 ? def.id : nil }
                            ))
                    } else {
                        // Structured fields (choice, date, number) are edited in
                        // the web app; show the value read-only here.
                        RichTextView(text: model.content?.section(def.id).text ?? "")
                    }
                }
            }
        }
    }

    /// The "filed in" pill. A note already in a space names it; one that
    /// isn't offers the list, so filing it is one tap rather than a trip
    /// through the ⋯ menu. With no spaces yet there is nothing to offer.
    @ViewBuilder
    private var spacePill: some View {
        if !app.spaces.isEmpty {
            let current = app.spaceOf[model.noteId]
            if let space = app.spaces.first(where: { $0.id == current }) {
                Button {
                    app.file(noteId: model.noteId, in: nil)
                } label: {
                    DSMetaPill(symbol: "folder", text: space.name)
                }
                .buttonStyle(.plain)
                .accessibilityHint("Take this note out of \(space.name)")
            } else {
                Menu {
                    ForEach(app.spaces) { space in
                        Button {
                            app.file(noteId: model.noteId, in: space.id)
                        } label: {
                            Label(space.name, systemImage: "folder")
                        }
                    }
                } label: {
                    DSMetaPill(symbol: "folder.badge.plus", text: "Add to space")
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
                    Text(turns.isEmpty ? "Nothing was said." : speakerSummary)
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                    Spacer()
                    Button {
                        copyToPasteboard(model.transcriptText())
                        copied = true
                        Task {
                            try? await Task.sleep(for: .seconds(1.5))
                            copied = false
                        }
                    } label: {
                        Label(copied ? "Copied" : "Copy", systemImage: copied ? "checkmark" : "doc.on.doc")
                    }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 13, height: 30))
                    .disabled(turns.isEmpty)
                }
                ForEach(turns) { turn in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 8) {
                            if model.diarized {
                                speakerName(turn)
                            }
                            Text(formatElapsed(ms: turn.startMs))
                                .font(.dsMono(11.5))
                                .foregroundStyle(DS.muted)
                        }
                        ForEach(Array(turn.paragraphs.enumerated()), id: \.offset) { _, paragraph in
                            Text(paragraph)
                                .font(.dsBody)
                                .foregroundStyle(DS.text1)
                                .lineSpacing(3)
                                .textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                        }
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

    /// A turn's speaker name; a tap asks for a new one.
    @ViewBuilder
    private func speakerName(_ turn: TranscriptTurn) -> some View {
        if let label = turn.speaker {
            Button {
                speakerDraft = model.displayName(for: turn)
                editingSpeaker = label
            } label: {
                HStack(spacing: 4) {
                    Text(model.displayName(for: turn))
                        .font(.dsDisplay(15, .medium))
                        .foregroundStyle(DS.accentText)
                    Image(systemName: "pencil")
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(DS.accentText.opacity(0.6))
                }
            }
            .buttonStyle(.plain)
            .disabled(model.renamingSpeaker)
            .accessibilityHint("Rename this speaker")
        } else {
            Text(unknownSpeakerName)
                .font(.dsDisplay(15, .medium))
                .italic()
                .foregroundStyle(DS.muted)
        }
    }

    private var speakerSummary: String {
        guard model.diarized else { return "Speakers were not told apart in this recording." }
        let count = model.speakerCount
        return (count <= 1 ? "1 speaker" : "\(count) speakers") + " · tap a name to rename"
    }

    // MARK: - States

    private var loading: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                DSSkeleton(height: 30, width: 240)
                DSSkeleton(height: 14, width: 180)
                Spacer().frame(height: 12)
                DSSkeleton(height: 72)
                DSSkeleton(height: 72)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, DS.gutter)
            .padding(.top, 12)
        }
    }

    private func failed(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: message)
            HStack {
                Button("Try again") { Task { await model.load() } }
                    .buttonStyle(DSButtonStyle(kind: .secondary, height: 36))
                Button("Open in web app") { app.openNoteInBrowser(model.noteId) }
                    .buttonStyle(DSButtonStyle(kind: .ghost, height: 36))
            }
            Spacer()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, DS.gutter)
        .padding(.top, 12)
    }
}

/// One free-text section.
///
/// A note is a document first: what the model wrote is typeset — headings,
/// nested bullets, checklists — rather than shown as the raw `- ` and
/// `**…**` a plain string used to carry. On a draft the document is also
/// the way in: tap it and the same words come back as their markdown
/// source in the seamless editor, and dismissing the keyboard sets them
/// again. A section with nothing in it skips straight to the editor —
/// there is no document to read yet, only a prompt to write one.
private struct SectionField: View {
    @Binding var text: String
    let name: String
    let placeholder: String
    let editable: Bool
    @Binding var editing: Bool

    var body: some View {
        if !editable {
            RichTextView(text: text)
        } else if editing || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            SectionEditor(text: $text, placeholder: placeholder, editable: true, focusNow: editing) {
                editing = false
            }
        } else {
            RichTextView(text: text)
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .padding(.horizontal, -8)
                .contentShape(Rectangle())
                .onTapGesture { editing = true }
                .accessibilityAddTraits(.isButton)
                .accessibilityLabel("Edit \(name)")
                .accessibilityAction { editing = true }
        }
    }
}

/// A seamless, auto-growing text area (`.textarea.seamless`): no chrome
/// until it is focused, then a faint surface behind it.
private struct SectionEditor: View {
    @Binding var text: String
    let placeholder: String
    let editable: Bool
    /// Take the keyboard as soon as this appears — it was opened by a tap.
    var focusNow = false
    var onDone: () -> Void = {}

    @FocusState private var focused: Bool

    var body: some View {
        TextField(editable ? placeholder : "Nothing entered.", text: $text, axis: .vertical)
            .textFieldStyle(.plain)
            .lineLimit(2...)
            .font(.dsBody)
            .foregroundStyle(DS.text1)
            .lineSpacing(3)
            .focused($focused)
            .disabled(!editable)
            .padding(.horizontal, 8)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .fill(focused ? DS.surface : .clear)
            )
            .overlay(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .strokeBorder(focused ? DS.text3.opacity(0.6) : .clear, lineWidth: 1)
            )
            .padding(.horizontal, -8)
            .onAppear { if focusNow { focused = true } }
            .onChange(of: focused) { _, isFocused in
                // Dismissing the keyboard closes the editor and the section
                // goes back to being read; the text was already saved on
                // every keystroke.
                if !isFocused, focusNow { onDone() }
            }
            .animation(.easeOut(duration: 0.12), value: focused)
    }
}
