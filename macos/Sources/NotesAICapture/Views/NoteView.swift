import AppKit
import SwiftUI

/// The note as a document, the way the web editor shows it: a slim bar
/// (status, save state, ⋯), the title, a meta line, Notes / Transcript
/// tabs, and one seamless text area per template section. Every note
/// autosaves until it is cancelled (history stays in the web app).
struct NoteView: View {
    @EnvironmentObject private var app: AppState
    @StateObject private var model: NoteViewModel
    @State private var confirmDelete = false
    @State private var shareByEmail = false
    @State private var shareWithClient = false
    @State private var confirmMarkDone = false
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
        .task(id: model.noteId) {
            // A re-label this note follows shows in the recents list too.
            model.onRelabellingChange = { [weak app] jobId, running in
                app?.setRelabelling(jobId: jobId, running)
            }
            await model.load()
        }
        .task(id: model.noteId) { await model.loadSharing() }
        .onChange(of: model.note?.title) { old, title in
            // The server's name for the note — the one a recording gets
            // once it has been heard — replaces this device's placeholder
            // in the recents and the notes list.
            guard let title, !title.isEmpty else { return }
            if let jobId = capture?.jobId { app.updateRecent(jobId: jobId, title: title) }
            if old != nil, old != title { Task { await app.refreshNotes() } }
        }
        .task(id: model.version) { await model.loadItems() }
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
        .sheet(isPresented: $shareWithClient) {
            ShareWithClientSheet(model: model, webAppURL: app.settings.webAppURL,
                                 onClose: { shareWithClient = false })
        }
        .onChange(of: app.pendingClientShare, initial: true) { _, pending in
            // The menu-bar popover's "Share with client…" lands here.
            if pending == model.noteId {
                app.pendingClientShare = nil
                shareWithClient = true
            }
        }
        .sheet(isPresented: $shareByEmail) {
            ShareEmailSheet(
                noteTitle: model.content?.title ?? "",
                send: { recipients, message in
                    await model.sendShareEmail(recipients: recipients, message: message)
                },
                onClose: { shareByEmail = false })
        }
        .alert("Mark all confirmed items done?", isPresented: $confirmMarkDone) {
            Button("Mark done") { Task { await model.markAllConfirmedDone() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Every open item that at least one recipient confirmed, and nobody disputed, is marked done.")
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
            if let note = model.note, note.status == .cancelled {
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
            // The client-facing path (Sprint 19): one link per recipient.
            .item("Share with client…", symbol: "paperplane", disabled: model.busy || !canManage) {
                shareWithClient = true
            },
            .item("Mark all confirmed items done", symbol: "checkmark.circle",
                  disabled: model.busy || !canManage
                      || !model.items.contains { $0.status == .open && $0.counts.confirms > 0 && $0.counts.disputes == 0 }) {
                confirmMarkDone = true
            },
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
            // Sprint 32: a suggestion's quote was clicked — show its turn.
            .onChange(of: model.revealedTurn) { _, reveal in
                guard let reveal else { return }
                withAnimation(.easeOut(duration: 0.25)) { proxy.scrollTo(reveal.turnId, anchor: .center) }
            }
        }
        // The composer sits over the document, under a short wash of the
        // page ground so a line of text never runs into it.
        .overlay(alignment: .bottom) {
            LinearGradient(colors: [DS.bg.opacity(0), DS.bg], startPoint: .top, endPoint: .bottom)
                .frame(height: 96)
                .allowsHitTesting(false)
                .overlay(alignment: .bottom) {
                    if model.selectedTurnIds.isEmpty { askBar } else { moveBar }
                }
        }
        .onChange(of: model.tab) { _, _ in model.endSelection() }
        .onChange(of: model.online) { _, online in
            if !online { model.endSelection() }
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

        if capture?.status == .complete || model.hasTranscript {
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
            if !model.items.isEmpty {
                // Sprint 20: the action items as objects, with what the
                // recipients did. The section text below stays the source.
                ActionItemsSection(model: model)
            }
            // Sprint 33: the engine, from the Notes tab. The button lives here
            // and nowhere else — a draft of ours, made from a recording, that
            // was never written up.
            if model.canGenerateSummary {
                HStack(alignment: .center, spacing: 12) {
                    Text("Create a structured summary from this conversation.")
                        .font(.dsBody)
                        .foregroundStyle(DS.muted)
                    Spacer(minLength: 0)
                    Button {
                        Task { await model.generateSummary() }
                    } label: {
                        if model.generating {
                            ProgressView().controlSize(.small).frame(width: 120)
                        } else {
                            Text("Generate Summary")
                        }
                    }
                    .buttonStyle(DSButtonStyle(kind: .primary, size: 12, height: 28))
                    .disabled(model.generating)
                }
                .dsCard()
            } else if let generation = model.generation, generation.isLive {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(generation.progressText)
                        .font(.dsBody)
                        .foregroundStyle(DS.muted)
                }
            } else if let generation = model.generation, model.editable,
                      generation.status == "failed" || generation.wroteNothing {
                HStack(alignment: .center, spacing: 10) {
                    DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill",
                             text: generation.wroteNothing
                                 ? GenerationView.nothingWrittenText : generation.failureText)
                    if generation.errorKind != "budget_exceeded" {
                        Button("Try again") { Task { await model.generateSummary() } }
                            .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
                            .disabled(model.generating)
                    }
                }
            }
            if let generation = model.generation, !generation.isLive {
                generationFacts(generation)
            }
            if let error = model.generationError {
                DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill", text: error)
            }
            if model.sections.isEmpty {
                Text("This note's template has no sections.")
                    .font(.dsBody)
                    .foregroundStyle(DS.muted)
            }
            if model.blocks.isEmpty, !model.sections.isEmpty {
                Text(model.hasTranscript
                     ? "No notes yet — the transcript is under the other tab."
                     : "Nothing here yet.")
                    .font(.dsBody)
                    .foregroundStyle(DS.muted)
            }

            // Structure follows content: one block per section the note
            // HAS, headed only when it has a title. Nothing is drawn for
            // being in the template.
            ForEach(model.blocks) { block in
                VStack(alignment: .leading, spacing: 6) {
                    if let title = block.title, !title.isEmpty {
                        // A "#" hangs in the gutter so the document's outline
                        // is legible at a glance; it sits outside the text
                        // column, so it never pushes the words in.
                        Text(title)
                            .font(.dsDisplay(18, .semibold))
                            .foregroundStyle(DS.text1)
                            .overlay(alignment: .leading) {
                                Text("#")
                                    .font(.dsMono(13))
                                    .foregroundStyle(DS.muted.opacity(0.45))
                                    .offset(x: -20)
                            }
                    }
                    if block.isFreeText {
                        SectionField(
                            text: Binding(
                                get: { model.content?.section(block.key).text ?? "" },
                                set: { model.setSectionText(block.key, $0) }
                            ),
                            name: block.name,
                            placeholder: block.placeholder,
                            editable: model.editable,
                            editing: Binding(
                                get: { editingSection == block.key },
                                set: { editingSection = $0 ? block.key : nil }
                            ))
                    } else {
                        // Structured fields (choice, date, number) are edited in
                        // the web app; show the value read-only here.
                        RichTextView(text: model.content?.section(block.key).text ?? "", size: DS.docText)
                    }
                }
            }
        }
    }

    // MARK: - What the engine made of the recording (Q3)

    /// Under the status line, quietly: what the recording was taken to be
    /// (nothing for a meeting), and the passages left out of the note —
    /// "Not included: 00:45–00:52 (background speech)". Each range opens
    /// the transcript at that moment when there is a timed one to open.
    @ViewBuilder
    private func generationFacts(_ generation: GenerationView) -> some View {
        let label = generation.recordingTypeLabel
        let excluded = generation.isFinished && !generation.wroteNothing
            ? generation.shownExcluded : (items: [], more: 0)
        if label != nil || !excluded.items.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                if let label {
                    Text(label)
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                }
                if !excluded.items.isEmpty {
                    Text(notIncludedText(excluded.items, more: excluded.more,
                                         linked: model.canSeekTranscript))
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .tint(DS.muted)
                        .fixedSize(horizontal: false, vertical: true)
                        .environment(\.openURL, OpenURLAction { url in
                            guard url.scheme == Self.seekScheme,
                                  let ms = Int(url.absoluteString.dropFirst(Self.seekScheme.count + 1))
                            else { return .systemAction }
                            Task { await model.seekTranscript(to: ms) }
                            return .handled
                        })
                }
            }
        }
    }

    /// Links in the "Not included" line are these, handled in place.
    private static let seekScheme = "notesai-seek"

    private func notIncludedText(_ items: [GenerationView.ExcludedItem], more: Int,
                                 linked: Bool) -> AttributedString {
        var line = AttributedString("Not included: ")
        for (index, item) in items.enumerated() {
            if index > 0 { line += AttributedString(", ") }
            var part = AttributedString(item.text)
            if linked, let url = URL(string: "\(Self.seekScheme):\(item.startMs)") {
                part.link = url
                part.underlineStyle = .single
            }
            line += part
        }
        if more > 0 { line += AttributedString(" +\(more) more") }
        return line
    }

    // MARK: - Transcript

    @ViewBuilder
    private var transcript: some View {
        VStack(alignment: .leading, spacing: 18) {
            if model.jobId == nil || (model.transcriptError != nil && !model.textTurns.isEmpty) {
                ForEach(model.textTurns) { turn in
                    HStack(alignment: .top, spacing: 12) {
                        SpeakerAvatar(name: turn.speaker ?? unknownSpeakerName)
                        VStack(alignment: .leading, spacing: 3) {
                            if let speaker = turn.speaker {
                                TextSpeakerName(name: speaker, model: model,
                                                editingLabel: $editingSpeaker, draft: $speakerDraft)
                            } else {
                                Text(unknownSpeakerName)
                                    .font(.dsDisplay(15, .semibold))
                                    .italic()
                                    .foregroundStyle(DS.muted)
                            }
                            Text(turn.text)
                                .font(.dsDocBody)
                                .foregroundStyle(DS.text1)
                                .lineSpacing(4)
                                .textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            } else if let error = model.transcriptError {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
            } else if let turns = model.turns {
                if model.diarized, !model.speakers.isEmpty {
                    SpeakerRosterView(model: model) { label in
                        speakerDraft = model.name(for: label)
                        editingSpeaker = label
                    }
                }
                RememberTermBanner(model: model)
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
                    HStack(alignment: .top, spacing: 12) {
                    if model.diarized { turnAvatar(turn) }
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
                    Spacer(minLength: 0)
                    }
                    .padding(6)
                    .background(
                        RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                            .fill(turnTint(turn))
                    )
                    .padding(-6)
                    .contentShape(Rectangle())
                    // Sprint 30: ⌘-click picks turns for a move together.
                    .simultaneousGesture(TapGesture().modifiers(.command).onEnded {
                        if model.canEditSpeakers { model.toggleSelection(turn) }
                    })
                    .accessibilityElement(children: .contain)
                    .accessibilityAddTraits(model.selectedTurnIds.contains(turn.id) ? .isSelected : [])
                    .animation(.easeOut(duration: 0.2), value: model.highlightedTurnId)
                    .id(turn.id)
                }
            } else {
                DSSkeleton(height: 56)
                DSSkeleton(height: 56)
                DSSkeleton(height: 56)
            }
        }
        .task { await model.loadTranscript() }
    }

    /// A picked turn, or the one a suggestion's quote pointed at (2 s).
    private func turnTint(_ turn: TranscriptTurn) -> Color {
        if model.selectedTurnIds.contains(turn.id) { return DS.accent.opacity(0.1) }
        if model.highlightedTurnId == turn.id { return DS.accent.opacity(0.16) }
        return .clear
    }

    private var speakerSummary: String {
        guard model.diarized else { return "Speakers were not told apart in this recording." }
        let count = model.speakerCount
        return (count <= 1 ? "1 speaker" : "\(count) speakers") + " · click a name to rename"
            + (model.canMoveTurns ? " · ⌘-click turns to move them" : "")
    }

    /// The turn's avatar: a click offers to move the turn to another
    /// speaker (Sprint 30). A "?" marks a turn where people talked over
    /// each other.
    @ViewBuilder
    private func turnAvatar(_ turn: TranscriptTurn) -> some View {
        let avatar = SpeakerAvatar(name: model.displayName(for: turn))
            .overlay(alignment: .bottomTrailing) {
                if turn.isUncertain { UncertainMarker() }
            }
        if model.canMove(turn) {
            Menu {
                Section("Move this turn to") {
                    moveButtons(for: [turn])
                }
                // Sprint 32: the keyboard's way to what ⌘-click does.
                Divider()
                Button(model.selectedTurnIds.contains(turn.id) ? "Deselect this turn" : "Select to move with others") {
                    model.toggleSelection(turn)
                }
            } label: {
                avatar
            }
            .menuStyle(.button)
            .buttonStyle(.plain)
            .menuIndicator(.hidden)
            .fixedSize()
            .disabled(!model.canEditSpeakers)
            .help(turn.isUncertain
                  ? "\(UncertainMarker.explanation) Click to move this turn to another speaker."
                  : "Move this turn to another speaker")
            .accessibilityLabel("Move this turn to another speaker")
            .accessibilityValue(turn.isUncertain ? UncertainMarker.explanation : "")
        } else {
            avatar
        }
    }

    /// Where turns can go: the other speakers, a new one, Unknown.
    @ViewBuilder
    private func moveButtons(for moving: [TranscriptTurn]) -> some View {
        ForEach(model.moveTargets(for: moving), id: \.self) { label in
            Button(model.name(for: label)) {
                Task { await model.moveTurns(moving, to: .speaker(label)) }
            }
        }
        Divider()
        if model.canAddSpeaker {
            Button("New speaker") { Task { await model.moveTurns(moving, to: .new) } }
        }
        if model.canMoveToUnknown(moving) {
            Button("Unknown") { Task { await model.moveTurns(moving, to: .unknown) } }
        }
    }

    /// The ⌘-click selection's action bar: "Move N turns to ▸".
    private var moveBar: some View {
        HStack(spacing: 10) {
            Text("\(model.selectedTurnIds.count) selected")
                .font(.ds(12.5, .medium))
                .foregroundStyle(DS.text2)
            Menu {
                moveButtons(for: model.selectedTurns)
            } label: {
                HStack(spacing: 4) {
                    Text(model.moveSelectionTitle)
                    Image(systemName: "chevron.right")
                }
            }
            .menuStyle(.button)
            .fixedSize()
            .disabled(!model.canEditSpeakers)
            .accessibilityLabel(model.moveSelectionTitle)
            .accessibilityHint("Choose the speaker these turns belong to")
            Button("Clear") { model.endSelection() }
                .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 26))
                .keyboardShortcut(.cancelAction)
                .accessibilityLabel("Clear selection")
                .help("Clear the selection (Esc)")
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Selected turns")
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: DS.radiusXl, style: .continuous)
                .fill(DS.surface)
                .shadow(color: .black.opacity(0.14), radius: 18, y: 6)
        )
        .padding(.bottom, 16)
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
    /// The pointer is over the completion list: losing focus to a click
    /// there is a pick, not a commit of what was typed.
    @State private var overCompletions = false

    var body: some View {
        if let label = turn.speaker {
            if editingLabel == label {
                VStack(alignment: .leading, spacing: 4) {
                TextField("Name", text: $draft)
                    .textFieldStyle(.plain)
                    .font(.dsDisplay(15, .semibold))
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
                        if !isFocused, editingLabel == label, !overCompletions { commit(label) }
                    }
                completions(label)
                }
            } else {
                Button {
                    draft = model.displayName(for: turn)
                    editingLabel = label
                } label: {
                    Text(model.displayName(for: turn))
                        .font(.dsDisplay(15, .semibold))
                        .foregroundStyle(hover ? DS.accentText : DS.text1)
                        .underline(hover, pattern: .dot, color: DS.accentText)
                }
                .buttonStyle(.plain)
                .disabled(model.renamingSpeaker)
                .help("Rename this speaker")
                .onHover { hover = $0 }
                .contextMenu {
                    Button("Rename…") {
                        draft = model.displayName(for: turn)
                        editingLabel = label
                    }
                    MergeMenu(model: model, label: label)
                }
            }
        } else {
            Text(unknownSpeakerName)
                .font(.dsDisplay(15, .semibold))
                .italic()
                .foregroundStyle(DS.muted)
        }
    }

    /// Sprint 30: the calendar's invitees not yet used on another speaker,
    /// narrowed by what is typed. A click names the speaker.
    @ViewBuilder
    private func completions(_ label: String) -> some View {
        let names = model.nameCompletions(for: label, typed: draft)
        if !names.isEmpty {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(names, id: \.self) { name in
                    Button {
                        overCompletions = false
                        editingLabel = nil
                        Task { await model.renameSpeaker(label: label, to: name, picked: true) }
                    } label: {
                        HStack(spacing: 8) {
                            SpeakerAvatar(name: name).scaleEffect(0.75).frame(width: 20, height: 20)
                            Text(name).font(.ds(13)).foregroundStyle(DS.text1)
                            Spacer(minLength: 0)
                        }
                        .padding(.horizontal, 7)
                        .padding(.vertical, 3)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            .frame(width: 200, alignment: .leading)
            .padding(.vertical, 3)
            .background(RoundedRectangle(cornerRadius: 6, style: .continuous).fill(DS.surface))
            .overlay(
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .strokeBorder(DS.text3.opacity(0.35), lineWidth: 1)
            )
            .onHover { overCompletions = $0 }
            .accessibilityLabel("Invited people")
        }
    }

    private func commit(_ label: String) {
        let name = draft
        editingLabel = nil
        Task { await model.renameSpeaker(label: label, to: name, picked: false) }
    }
}


/// Initials in a tinted circle; the tint is a stable function of the
/// name (same palette and hash as the web), so a person keeps their
/// colour everywhere.
struct SpeakerAvatar: View {
    let name: String

    private static let tints: [Color] = [
        Color.ds("4f7a5e", "4f7a5e"), Color.ds("b5673c", "b5673c"), Color.ds("8a6d2f", "8a6d2f"),
        Color.ds("4a6d8c", "4a6d8c"), Color.ds("7a5a8c", "7a5a8c"), Color.ds("3f7f7a", "3f7f7a"),
    ]

    private var tint: Color {
        let h = name.unicodeScalars.reduce(0) { ($0 + Int($1.value)) % Self.tints.count }
        return Self.tints[h]
    }

    private var initials: String {
        let words = name.split(whereSeparator: \.isWhitespace).map(String.init)
        let pick = words.count >= 2 ? [words[0], words[words.count - 1]] : Array(words.prefix(1))
        let out = pick.compactMap { $0.first.map { String($0).uppercased() } }.joined()
        return out.isEmpty ? "•" : out
    }

    var body: some View {
        Text(initials)
            .font(.dsDisplay(11.5, .semibold))
            .foregroundStyle(tint)
            .frame(width: 28, height: 28)
            .background(Circle().fill(tint.opacity(0.16)))
            .padding(.top, 1)
    }
}

/// A speaker name in a text-only transcript: a click turns it into a
/// field; Return (or clicking away) rewrites every turn of that speaker
/// in the note, which autosaves. Escape cancels.
private struct TextSpeakerName: View {
    let name: String
    @ObservedObject var model: NoteViewModel
    @Binding var editingLabel: String?
    @Binding var draft: String

    @FocusState private var focused: Bool
    @State private var hover = false

    var body: some View {
        if editingLabel == name {
            TextField("Name", text: $draft)
                .textFieldStyle(.plain)
                .font(.dsDisplay(15, .semibold))
                .foregroundStyle(DS.text1)
                .padding(.horizontal, 7)
                .padding(.vertical, 2)
                .frame(width: 200)
                .background(RoundedRectangle(cornerRadius: 6, style: .continuous).fill(DS.surface))
                .overlay(RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .strokeBorder(DS.text3.opacity(0.6), lineWidth: 1))
                .focused($focused)
                .onAppear { focused = true }
                .onSubmit { commit() }
                .onExitCommand { editingLabel = nil }
                .onChange(of: focused) { _, isFocused in
                    if !isFocused, editingLabel == name { commit() }
                }
        } else {
            Button {
                draft = name
                editingLabel = name
            } label: {
                Text(name)
                    .font(.dsDisplay(15, .semibold))
                    .foregroundStyle(hover ? DS.accentText : DS.text1)
                    .underline(hover, pattern: .dot, color: DS.accentText)
            }
            .buttonStyle(.plain)
            .help("Rename this speaker")
            .onHover { hover = $0 }
        }
    }

    private func commit() {
        let to = draft
        editingLabel = nil
        Task { await model.renameSpeaker(label: name, to: to) }
    }
}

/// Sprint 30: a small "?" on a turn's avatar — the attribution is a guess
/// because people talked over each other.
struct UncertainMarker: View {
    static let explanation = "People talked over each other here."

    var body: some View {
        Text("?")
            .font(.system(size: 9, weight: .bold))
            .foregroundStyle(DS.inkText)
            .frame(width: 13, height: 13)
            .background(Circle().fill(DS.warn))
            .offset(x: 3, y: 3)
            .help(Self.explanation)
            .accessibilityLabel(Self.explanation)
    }
}
