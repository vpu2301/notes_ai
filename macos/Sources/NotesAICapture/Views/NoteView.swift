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
    @State private var shareByEmail = false
    /// Which speaker label is being renamed inline, and the text so far.
    @State private var editingSpeaker: String?
    @State private var speakerDraft = ""
    /// What is typed in the ask bar at the bottom.
    @State private var askDraft = ""
    /// Which section is open in its editor. A draft reads as a document
    /// until you click into one, and only one is ever open at a time.
    @State private var editingSection: String?

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
            // The way back out of the document. The sidebar has Home too,
            // but a note is read full-width and the way out should be
            // where the eyes already are.
            Button { app.selection = nil } label: {
                Label("Home", systemImage: "chevron.left")
            }
            .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 26))
            .keyboardShortcut("[", modifiers: .command)
            .help("Back to home (⌘[)")
            if let note = model.note, note.status != .draft {
                DSChip(text: note.status.label, tint: note.status.tint, soft: note.status.soft)
            }
            if model.conflict {
                DSChip(text: "Out of date", tint: DS.warn, soft: DS.warnSoft)
            }
            if let label = model.oversightLabel {
                DSChip(text: label, tint: DS.info, soft: DS.infoSoft)
                    .help("You can see this note because you run this workspace. This view is recorded.")
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
        if !model.chat.isEmpty {
            items.append(.separator)
            items.append(.item("Clear chat", symbol: "bubble.left.and.text.bubble.right") {
                model.clearChat()
            })
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
        ScrollViewReader { proxy in
            ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        documentBody
                        if !model.chat.isEmpty || model.asking || model.askError != nil {
                            askThread
                                .padding(.top, 36)
                        }
                        Color.clear.frame(height: 1).id("ask-end")
                    }
                .frame(maxWidth: DS.docWidth, alignment: .leading)
                .frame(maxWidth: .infinity)
                .padding(.horizontal, 40)
                .padding(.top, 28)
                // Room for the composer floating over the foot of the page,
                // so the last line of the note is never under it.
                .padding(.bottom, 96)
            }
            .onChange(of: model.chat.count) { _, _ in
                withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo("ask-end", anchor: .bottom) }
            }
            .onChange(of: model.asking) { _, asking in
                if asking { withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo("ask-end", anchor: .bottom) } }
            }
        }
        // The composer sits over the document, under a short wash of the
        // page ground so a line of text never runs into it.
        .overlay(alignment: .bottom) {
            LinearGradient(colors: [DS.bg.opacity(0), DS.bg], startPoint: .top, endPoint: .bottom)
                .frame(height: 96)
                .allowsHitTesting(false)
                .overlay(alignment: .bottom) { askBar }
        }
    }

    /// Title, meta line, tabs and the section editors — the note itself.
    @ViewBuilder
    private var documentBody: some View {
        TextField("Untitled note", text: Binding(
            get: { model.content?.title ?? "" },
            set: { model.setTitle($0) }
        ))
        .textFieldStyle(.plain)
        .font(.dsDisplay(30))
        .foregroundStyle(DS.text1)
        .disabled(!model.editable)
        .padding(.bottom, 10)

        // The meta line is a row of pills, not a run of text: when it was
        // taken, what wrote it, where it is filed, what it is called. Only
        // the space is a control — the rest are the facts you want at a
        // glance without reading a sentence.
        if let note = model.note {
            HStack(spacing: 6) {
                DSMetaPill(symbol: "calendar", text: formatDateTime(note.createdAt))
                DSMetaPill(text: "Updated \(relativeTime(note.updatedAt))")
                if let template = model.templateName {
                    DSMetaPill(symbol: "sparkles", text: template, tone: .accent)
                        .help("The template this note was written from")
                }
                spacePill
                DSMetaPill(text: note.code, mono: true)
            }
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

    /// The "filed in" pill. A note already in a space names it; one that
    /// isn't offers the list, so filing it is one click rather than a trip
    /// through the ⋯ menu. With no spaces yet there is nothing to offer.
    @ViewBuilder
    private var spacePill: some View {
        if !app.spaces.isEmpty {
            let current = app.spaceOf[model.noteId]
            if let space = app.spaces.first(where: { $0.id == current }) {
                Button {
                    app.file(noteId: model.noteId, in: nil)
                } label: {
                    DSMetaPill(symbol: "folder", text: space.name, interactive: true)
                }
                .buttonStyle(.plain)
                .help("Take this note out of \(space.name)")
            } else {
                DSMenu(width: 220) {
                    app.spaces.map { space in
                        DSMenuItem.item(space.name, symbol: "folder") {
                            app.file(noteId: model.noteId, in: space.id)
                        }
                    }
                } label: {
                    DSMetaPill(symbol: "folder.badge.plus", text: "Add to space", interactive: true)
                }
            }
        }
    }

    // MARK: - Ask this note

    /// The thread: questions on the right in a quiet bubble, answers as
    /// plain text under a spark — one conversation about this note.
    private var askThread: some View {
        VStack(alignment: .leading, spacing: 14) {
            ForEach(model.chat) { message in
                switch message.role {
                case .user:
                    HStack {
                        Spacer(minLength: 80)
                        Text(message.text)
                            .font(.dsBody)
                            .foregroundStyle(DS.text1)
                            .textSelection(.enabled)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                            .background(
                                RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous)
                                    .fill(DS.surface2)
                            )
                    }
                case .assistant:
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: "sparkles")
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(DS.accentText)
                            .frame(width: 20, height: 20)
                        // An answer arrives as bullets and headings just as
                        // the note does, so it is typeset the same way.
                        RichTextView(text: message.text)
                    }
                }
            }
            if model.asking {
                HStack(spacing: 10) {
                    Image(systemName: "sparkles")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(DS.accentText)
                        .frame(width: 20, height: 20)
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
    /// Return sends. It is centred on the note's column, so it reads as
    /// part of the document rather than as a strip of window chrome.
    private var askBar: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Image(systemName: "sparkles")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(DS.accentText)
                TextField("Ask about this note…", text: $askDraft, axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(.ds(13.5))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1...4)
                    .onSubmit { sendQuestion() }
                Button { sendQuestion() } label: {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 12, weight: .semibold))
                        .frame(width: 8)
                }
                .buttonStyle(DSButtonStyle(kind: .primary, size: 12, height: 26))
                .disabled(model.asking || askDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .keyboardShortcut(.return, modifiers: .command)
                .help("Send (Return)")
            }
            .padding(.leading, 14)
            .padding(.trailing, 8)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: DS.radiusXl, style: .continuous)
                    .fill(DS.surface)
                    .shadow(color: .black.opacity(0.14), radius: 18, y: 6)
            )
            .overlay(
                RoundedRectangle(cornerRadius: DS.radiusXl, style: .continuous)
                    .strokeBorder(DS.line, lineWidth: DS.hairline)
            )
            .frame(maxWidth: DS.docWidth)
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 40)
            .padding(.bottom, 14)
            .padding(.top, 6)
        }
    }

    private func sendQuestion() {
        let question = askDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty, !model.asking else { return }
        askDraft = ""
        Task { await model.ask(question) }
    }

    private var sections: some View {
        VStack(alignment: .leading, spacing: 20) {
            if model.sections.isEmpty {
                Text("This note's template has no sections.")
                    .font(.dsBody)
                    .foregroundStyle(DS.muted)
            }
            ForEach(model.sections) { def in
                VStack(alignment: .leading, spacing: 6) {
                    // A "#" hangs in the gutter so the document's outline
                    // is legible at a glance; it sits outside the text
                    // column, so it never pushes the words in.
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(def.name)
                            .font(.dsDisplay(18, .semibold))
                            .foregroundStyle(DS.text1)
                            .overlay(alignment: .leading) {
                                Text("#")
                                    .font(.dsMono(13))
                                    .foregroundStyle(DS.muted.opacity(0.45))
                                    .offset(x: -20)
                            }
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
                        RichTextView(text: model.content?.section(def.id).text ?? "", size: DS.docText)
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
                    Text(turns.isEmpty ? "Nothing was said." : speakerSummary)
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
                            if model.diarized {
                                SpeakerName(turn: turn, model: model,
                                            editingLabel: $editingSpeaker, draft: $speakerDraft)
                            }
                            Text(formatElapsed(ms: turn.startMs))
                                .font(.dsMono(11))
                                .foregroundStyle(DS.muted)
                        }
                        ForEach(Array(turn.paragraphs.enumerated()), id: \.offset) { _, paragraph in
                            Text(paragraph)
                                .font(.dsDocBody)
                                .foregroundStyle(DS.text1)
                                .lineSpacing(4)
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

    private var speakerSummary: String {
        guard model.diarized else { return "Speakers were not told apart in this recording." }
        let count = model.speakerCount
        return (count <= 1 ? "1 speaker" : "\(count) speakers") + " · click a name to rename"
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
        .frame(maxWidth: DS.docWidth, alignment: .leading)
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
        .frame(maxWidth: DS.docWidth, alignment: .leading)
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 40)
        .padding(.top, 28)
    }

    private func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }
}

/// One free-text section.
///
/// A note is a document first: what the model wrote is typeset — headings,
/// nested bullets, checklists — rather than shown as the raw `- ` and
/// `**…**` a plain string used to carry. On a draft the document is also
/// the way in: click it and the same words come back as their markdown
/// source in the seamless editor, and leaving the field sets them again.
/// A section with nothing in it skips straight to the editor — there is
/// no document to read yet, only a prompt to write one.
private struct SectionField: View {
    @Binding var text: String
    let name: String
    let placeholder: String
    let editable: Bool
    @Binding var editing: Bool

    @State private var hover = false

    var body: some View {
        if !editable {
            RichTextView(text: text, size: DS.docText)
        } else if editing || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            SectionEditor(text: $text, placeholder: placeholder, editable: true, focusNow: editing) {
                editing = false
            }
        } else {
            RichTextView(text: text, size: DS.docText)
                .padding(.horizontal, 6)
                .padding(.vertical, 4)
                .background(
                    RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                        .fill(hover ? DS.surfaceHover : .clear)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                        .strokeBorder(hover ? DS.line2 : .clear, lineWidth: DS.hairline)
                )
                .padding(.horizontal, -6)
                .contentShape(Rectangle())
                .onHover { hover = $0 }
                // The rendered text is selectable, so a click on the words
                // starts a selection rather than the editor; the whole
                // block still opens it, and Return does from the keyboard.
                .onTapGesture(count: 2) { editing = true }
                .accessibilityAddTraits(.isButton)
                .accessibilityLabel("Edit \(name)")
                .accessibilityAction { editing = true }
                .overlay(alignment: .topTrailing) {
                    if hover {
                        Button { editing = true } label: {
                            Image(systemName: "pencil")
                                .font(.system(size: 11, weight: .medium))
                        }
                        .buttonStyle(DSIconButtonStyle())
                        .help("Edit this section")
                        .offset(x: 4, y: -6)
                        .transition(.opacity)
                    }
                }
                .animation(.easeOut(duration: 0.12), value: hover)
        }
    }
}

/// A seamless, auto-growing text area (`.textarea.seamless`): no chrome
/// until it is hovered or focused, then a faint surface behind it.
private struct SectionEditor: View {
    @Binding var text: String
    let placeholder: String
    let editable: Bool
    /// Take the caret as soon as this appears — it was opened by a click.
    var focusNow = false
    var onDone: () -> Void = {}

    @FocusState private var focused: Bool
    @State private var hover = false

    var body: some View {
        ZStack(alignment: .topLeading) {
            // TextEditor's intrinsic height counts newlines, not wrapped
            // lines; an invisible Text with the same metrics sets the real
            // height and the editor fills it.
            Text(text.isEmpty ? " " : text + " ")
                .font(.dsDocBody)
                .lineSpacing(4)
                .padding(.horizontal, 5)
                .padding(.vertical, 8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .opacity(0)
                .accessibilityHidden(true)
            if text.isEmpty {
                Text(editable ? placeholder : "Nothing entered.")
                    .font(.dsDocBody)
                    .foregroundStyle(DS.muted)
                    .padding(.horizontal, 5)
                    .padding(.vertical, 8)
                    .allowsHitTesting(false)
            }
            TextEditor(text: $text)
                .font(.dsDocBody)
                .foregroundStyle(DS.text1)
                .lineSpacing(4)
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
        .onAppear { if focusNow { focused = true } }
        .onChange(of: focused) { _, isFocused in
            // Clicking away closes the editor and the section goes back to
            // being read; the text was already saved on every keystroke.
            if !isFocused, focusNow { onDone() }
        }
        .animation(.easeOut(duration: 0.12), value: focused)
        .animation(.easeOut(duration: 0.12), value: hover)
    }
}


/// A turn's speaker name: a click turns it into a text field; Return (or
/// clicking away) saves the name to the job, Escape cancels.
private struct SpeakerName: View {
    let turn: TranscriptTurn
    @ObservedObject var model: NoteViewModel
    @Binding var editingLabel: String?
    @Binding var draft: String

    @FocusState private var focused: Bool
    @State private var hover = false

    var body: some View {
        if let label = turn.speaker {
            if editingLabel == label {
                TextField("Name", text: $draft)
                    .textFieldStyle(.plain)
                    .font(.dsDisplay(13.5, .medium))
                    .foregroundStyle(DS.text1)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 2)
                    .frame(width: 200)
                    .background(
                        RoundedRectangle(cornerRadius: 6, style: .continuous).fill(DS.surface)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: 6, style: .continuous)
                            .strokeBorder(DS.text3.opacity(0.6), lineWidth: 1)
                    )
                    .focused($focused)
                    .onAppear { focused = true }
                    .onSubmit { commit(label) }
                    .onExitCommand { editingLabel = nil }
                    .onChange(of: focused) { _, isFocused in
                        if !isFocused, editingLabel == label { commit(label) }
                    }
            } else {
                Button {
                    draft = model.displayName(for: turn)
                    editingLabel = label
                } label: {
                    Text(model.displayName(for: turn))
                        .font(.dsDisplay(13.5, .medium))
                        .foregroundStyle(DS.accentText)
                        .underline(hover, pattern: .dot, color: DS.accentText)
                }
                .buttonStyle(.plain)
                .disabled(model.renamingSpeaker)
                .help("Rename this speaker")
                .onHover { hover = $0 }
            }
        } else {
            Text(unknownSpeakerName)
                .font(.dsDisplay(13.5, .medium))
                .italic()
                .foregroundStyle(DS.muted)
        }
    }

    private func commit(_ label: String) {
        let name = draft
        editingLabel = nil
        Task { await model.renameSpeaker(label: label, to: name) }
    }
}
