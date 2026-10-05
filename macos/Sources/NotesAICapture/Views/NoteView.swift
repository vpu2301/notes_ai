import AppKit
import SwiftUI

/// The note as a document, as the web editor shows it: slim bar, title, meta line, Notes / Transcript tabs, one text area per section. Autosaves until cancelled.
struct NoteView: View {
    @EnvironmentObject private var app: AppState
    @StateObject private var model: NoteViewModel
    @State private var confirmDelete = false
    @State private var shareByEmail = false
    @State private var shareWithClient = false
    @State private var confirmMarkDone = false
    @State private var reviewingSpellings = false
    /// Which speaker label is being renamed inline, and the text so far.
    @State private var editingSpeaker: String?
    @State private var speakerDraft = ""
    /// What is typed in the ask bar at the bottom.
    @State private var askDraft = ""
    @FocusState private var askFocused: Bool
    /// Which section is open in its editor; only one at a time.
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
            // The server's name for the note replaces this device's placeholder in the lists.
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
            // The way back out of the document, where the eyes already are.
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
            // The client-facing path: one link per recipient.
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
            // One entry: colleague or outsider is the server's problem.
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
        items.append(.item(model.history == nil ? "History" : "Hide history", symbol: "clock.arrow.circlepath",
                           disabled: model.historyLoading) {
            Task { await model.toggleHistory() }
        })
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
                        if model.viewing == nil, !model.chat.isEmpty || model.asking || model.askError != nil {
                            askThread
                                .padding(.top, 36)
                        }
                        Color.clear.frame(height: 1).id("ask-end")
                    }
                .frame(maxWidth: DS.docWidth, alignment: .leading)
                .frame(maxWidth: .infinity)
                .padding(.horizontal, 40)
                .padding(.top, 28)
                .padding(.bottom, 24)
            }
            .onChange(of: model.chat.count) { _, _ in
                withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo("ask-end", anchor: .bottom) }
            }
            .onChange(of: model.asking) { _, asking in
                if asking { withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo("ask-end", anchor: .bottom) } }
            }
            // A suggestion's quote was clicked — show its turn.
            .onChange(of: model.revealedTurn) { _, reveal in
                guard let reveal else { return }
                withAnimation(.easeOut(duration: 0.25)) { proxy.scrollTo(reveal.turnId, anchor: .center) }
            }
        }
        // The composer is a fixed bottom inset: the document scrolls above it, never under it.
        .safeAreaInset(edge: .bottom, spacing: 0) {
            Group {
                if !model.selectedTurnIds.isEmpty {
                    moveBar
                } else if model.viewing == nil {
                    askBar
                }
            }
            .frame(maxWidth: .infinity)
            .background(
                LinearGradient(colors: [DS.bg.opacity(0), DS.bg], startPoint: .top, endPoint: .bottom)
                    .allowsHitTesting(false)
            )
        }
        .onChange(of: model.tab) { _, _ in model.endSelection() }
        .onChange(of: model.online) { _, online in
            if !online { model.endSelection() }
        }
    }

    /// Title, meta line, tabs and the section editors — the note itself.
    @ViewBuilder
    private var documentBody: some View {
        // Vertical, so a long title wraps; a pasted line break becomes a space.
        TextField("Untitled note", text: Binding(
            get: { model.content?.title ?? "" },
            set: { model.setTitle($0.replacingOccurrences(of: "\n", with: " ")) }
        ), axis: .vertical)
        .textFieldStyle(.plain)
        .font(.dsSerif(38))
        .tracking(-0.7)
        .lineLimit(1...6)
        .fixedSize(horizontal: false, vertical: true)
        .foregroundStyle(DS.text1)
        .disabled(!model.editableNow)
        .padding(.bottom, 6)

        // The meta line is a row of quiet, unframed facts; only the space is a control.
        if let note = model.note {
            HStack(spacing: 2) {
                DSMetaPill(symbol: "calendar", text: formatDateTime(note.createdAt))
                DSMetaPill(text: "Updated \(relativeTime(note.updatedAt))")
                if let template = model.templateName {
                    DSMetaPill(symbol: "sparkles", text: template, tone: .accent)
                        .help("The template this note was written from")
                }
                spacePill
                DSMetaPill(text: note.code, mono: true)
            }
            .padding(.leading, -8)
            .padding(.bottom, 14)
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

        // Reading an old version: say so, offer the way back. The tabs stay.
        if let viewing = model.viewing {
            HStack(spacing: 10) {
                DSNotice(tone: .info, symbol: "clock.arrow.circlepath",
                         text: "Reading version \(viewing.versionNumber) from \(formatDateTime(viewing.createdAt)). Nothing here can be edited.")
                Button("Back to current") { model.backToCurrent() }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
            }
            .padding(.bottom, 16)
        }

        if model.history != nil {
            HistoryPanel(model: model)
                .padding(.bottom, 16)
        }

        // Notes, the transcript, and what a client would see — the web's tabs, in order.
        DSSegmentedPill(options: tabOptions, selection: $model.tab, height: 36)
            .padding(.bottom, 20)
            .onChange(of: model.hasTranscript) { _, has in
                if !has, model.tab == .transcript { model.tab = .notes }
            }

        switch model.tab {
        case .notes: sections
        case .transcript: transcript
        case .clientVersion: ClientVersionView(model: model)
        }
    }

    private var tabOptions: [DSSegmentedPill<NoteViewModel.Tab>.Option] {
        var options: [DSSegmentedPill<NoteViewModel.Tab>.Option] = [.init(.notes, label: "Notes")]
        if capture?.status == .complete || model.hasTranscript {
            options.append(.init(.transcript, label: "Transcript"))
        }
        options.append(.init(.clientVersion, label: "Client version",
                             help: "What someone outside the workspace sees"))
        return options
    }

    /// The "filed in" pill: names the space, or offers the list (one click to file). Nothing with no spaces yet.
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

    /// The thread: questions on the right in a bubble, answers as plain text under a spark.
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
                            .font(.dsIcon(12, .medium))
                            .foregroundStyle(DS.accentText)
                            .frame(width: 20, height: 20)
                        // An answer is typeset like the note.
                        RichTextView(text: message.text)
                    }
                }
            }
            if model.asking {
                HStack(spacing: 10) {
                    Image(systemName: "sparkles")
                        .font(.dsIcon(12, .medium))
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

    /// The composer floating over the foot of the document: field on top, tool row under. Return sends. Centred on the note's column.
    private var askBar: some View {
        VStack(alignment: .leading, spacing: 6) {
            TextField("Ask about this note…", text: $askDraft, axis: .vertical)
                .textFieldStyle(.plain)
                .font(.ds(15))
                .foregroundStyle(DS.text1)
                .lineLimit(1...8)
                .focused($askFocused)
                .onSubmit { sendQuestion() }
            HStack(spacing: 8) {
                HStack(spacing: 6) {
                    Image(systemName: "sparkles")
                        .font(.dsIcon(12, .medium))
                        .foregroundStyle(DS.accentText)
                    Text("This note")
                        .font(.ds(13))
                        .foregroundStyle(DS.text3)
                }
                Spacer(minLength: 0)
                Button { sendQuestion() } label: {
                    Image(systemName: "arrow.up")
                        .font(.dsIcon(13, .semibold))
                        .foregroundStyle(DS.inkText)
                        .frame(width: 32, height: 32)
                        .background(
                            RoundedRectangle(cornerRadius: DS.radiusSm + 2, style: .continuous)
                                .fill(DS.ink)
                        )
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(askEmpty)
                .opacity(askEmpty ? 0.35 : 1)
                .keyboardShortcut(.return, modifiers: .command)
                .help("Send (Return)")
                .accessibilityLabel("Send")
            }
        }
        .padding(.top, 14)
        .padding(.leading, 16)
        .padding(.trailing, 12)
        .padding(.bottom, 10)
        .background(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .fill(DS.surface)
                .shadow(color: .black.opacity(askFocused ? 0.16 : 0.10), radius: askFocused ? 14 : 10, y: 6)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .strokeBorder(askFocused ? DS.lineHover : DS.line, lineWidth: DS.hairline)
        )
        .contentShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
        .onTapGesture { askFocused = true }
        .animation(.easeOut(duration: 0.15), value: askFocused)
        .frame(maxWidth: DS.docWidth)
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 40)
        .padding(.bottom, 14)
        .padding(.top, 6)
    }

    private var askEmpty: Bool {
        model.asking || askDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
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
                // The action items as objects, with what recipients did. The section text stays the source.
                ActionItemsSection(model: model)
            }
            // The engine, from the Notes tab and nowhere else.
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
                    if generation.errorKind == "processor_unacknowledged" {
                        dataSettingsButton
                    } else if generation.errorKind != "budget_exceeded" {
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
                HStack(alignment: .center, spacing: 10) {
                    DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill", text: error)
                    if model.generationErrorCode == "processor_unacknowledged" { dataSettingsButton }
                }
            }
            // How much of a generated note to show, names the engine respelled, and what the last meeting left open.
            if model.generated {
                DSSegmentedPill(
                    options: NoteViewModel.DetailLevel.allCases.map { .init($0, label: $0.label) },
                    selection: Binding(get: { model.detail }, set: { model.setDetail($0) }),
                    height: 26)
                .accessibilityLabel("How much to show")
            }
            if model.generated, model.editableNow {
                CorrectionsPanelView(model: model)
            }
            if model.viewing == nil {
                CarriedItemsView(model: model, readOnly: !model.editableNow)
            }
            if model.sections.isEmpty {
                Text("This note's template has no sections.")
                    .font(.dsBody)
                    .foregroundStyle(DS.muted)
            }
            if model.visibleBlocks.isEmpty, !model.sections.isEmpty {
                Text(model.hasTranscript
                     ? "No notes yet — the transcript is under the other tab."
                     : "Nothing here yet.")
                    .font(.dsBody)
                    .foregroundStyle(DS.muted)
            }

            // One block per section the note HAS, headed only when it has a title.
            let shown = model.viewing?.content ?? model.content
            let alsoSaid = model.alsoSaid
            ForEach(model.visibleBlocks) { block in
                VStack(alignment: .leading, spacing: 6) {
                    if let title = block.title, !title.isEmpty {
                        // A "#" hangs in the gutter, outside the text column.
                        // Section names are the document's headings: the title's serif, a size down.
                        Text(title)
                            .font(.dsSerif(20))
                            .tracking(-0.2)
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
                                get: { shown?.section(block.key).text ?? "" },
                                set: { model.setSectionText(block.key, $0) }
                            ),
                            name: block.name,
                            placeholder: block.placeholder,
                            editable: model.editableNow,
                            editing: Binding(
                                get: { editingSection == block.key },
                                set: { editingSection = $0 ? block.key : nil }
                            ),
                            lineExtra: lineExtra)
                    } else {
                        // Structured fields are edited in the web app; read-only here.
                        RichTextView(text: shown?.section(block.key).text ?? "", size: DS.docText)
                    }
                    if let extra = alsoSaid[block.key], !extra.isEmpty {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Also said")
                                .font(.dsMeta)
                                .foregroundStyle(DS.muted)
                            ForEach(extra) { row in
                                HStack(alignment: .firstTextBaseline, spacing: 7) {
                                    Circle().fill(DS.muted).frame(width: 4, height: 4).offset(y: -1)
                                        .frame(width: 14, alignment: .leading)
                                    Text(row.text)
                                        .font(.ds(DS.docText))
                                        .foregroundStyle(DS.text2)
                                        .lineSpacing(3)
                                        .fixedSize(horizontal: false, vertical: true)
                                    LineEvidenceView(model: model, row: row)
                                }
                            }
                        }
                        .padding(.top, 6)
                    }
                }
            }
        }
    }

    /// The chip and the quote behind a generated line, from the line's own text — nothing positional.
    private var lineExtra: ((String) -> AnyView?)? {
        guard model.generated else { return nil }
        return { raw in
            guard let row = model.row(forLine: raw) else { return nil }
            return AnyView(LineEvidenceView(model: model, row: row))
        }
    }

    /// The gate an admin lifts on the Data & AI tab, offered beside the sentence that names it.
    private var dataSettingsButton: some View {
        Button("Open Data & AI settings") {
            app.settingsTab = .dataAI
            app.settingsPresented = true
        }
        .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
    }

    // MARK: - What the engine made of the recording (Q3)

    /// Under the status line: what the recording was taken to be, and the passages left out ("Not included: …"). Each range opens the transcript there.
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

    /// Under the transcript's status line: speech that did not make it in, and why. A range inside the recording opens the transcript there.
    private func notTranscribed(_ line: CoverageGapsFormatter.Line) -> some View {
        var text = AttributedString("Not transcribed: ")
        for (index, item) in line.items.enumerated() {
            if index > 0 { text += AttributedString(", ") }
            var part = AttributedString(item.text)
            if item.seekable, model.canSeekTranscript,
               let url = URL(string: "\(Self.seekScheme):\(item.startMs)") {
                part.link = url
                part.underlineStyle = .single
            }
            text += part
        }
        if line.more > 0 { text += AttributedString(" +\(line.more) more") }
        return Text(text)
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
                if let banner = model.spellingBanner {
                    HStack(spacing: 8) {
                        DSNotice(tone: .info, symbol: "textformat.abc", text: banner.text)
                        Button(banner.action) { reviewingSpellings = true }
                            .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 26))
                    }
                }
                if let line = model.coverageLine {
                    notTranscribed(line)
                }
                ForEach(turns) { turn in
                    ForEach(model.markers(before: turn)) { marker in
                        NoiseMarkerLine(marker: marker, language: model.transcriptLanguage)
                    }
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
                            Text(EntityCorrection.underlined(paragraph, model.entityCorrections))
                                .font(.dsDocBody)
                                .foregroundStyle(DS.text1)
                                .lineSpacing(4)
                                .textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                                .help(EntityCorrection.paragraphHelp(paragraph, model.entityCorrections,
                                                                     language: model.transcriptLanguage))
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
                    // ⌘-click picks turns for a move together.
                    .simultaneousGesture(TapGesture().modifiers(.command).onEnded {
                        if model.canEditSpeakers { model.toggleSelection(turn) }
                    })
                    .accessibilityElement(children: .contain)
                    .accessibilityAddTraits(model.selectedTurnIds.contains(turn.id) ? .isSelected : [])
                    .animation(.easeOut(duration: 0.2), value: model.highlightedTurnId)
                    .id(turn.id)
                }
                ForEach(model.trailingMarkers) { marker in
                    NoiseMarkerLine(marker: marker, language: model.transcriptLanguage)
                }
            } else {
                DSSkeleton(height: 56)
                DSSkeleton(height: 56)
                DSSkeleton(height: 56)
            }
        }
        .task { await model.loadTranscript() }
        .sheet(isPresented: $reviewingSpellings) {
            EntityReviewSheetView(model: model)
        }
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

    /// The turn's avatar: a click offers to move the turn. A "?" marks overlapping speech.
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
                // The keyboard's way to what ⌘-click does.
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

/// One free-text section. The document is typeset (headings, bullets, checklists);
/// on a draft a click brings the markdown source back in the seamless editor.
/// An empty section skips straight to the editor.
private struct SectionField: View {
    @Binding var text: String
    let name: String
    let placeholder: String
    let editable: Bool
    @Binding var editing: Bool
    var lineExtra: ((String) -> AnyView?)? = nil

    @State private var hover = false

    var body: some View {
        if !editable {
            RichTextView(text: text, size: DS.docText, lineExtra: lineExtra)
        } else if editing || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            SectionEditor(text: $text, placeholder: placeholder, editable: true, focusNow: editing) {
                editing = false
            }
        } else {
            RichTextView(text: text, size: DS.docText, lineExtra: lineExtra)
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
                // The rendered text is selectable, so a single click selects; the block opens on double click, Return from the keyboard.
                .onTapGesture(count: 2) { editing = true }
                .accessibilityAddTraits(.isButton)
                .accessibilityLabel("Edit \(name)")
                .accessibilityAction { editing = true }
                .overlay(alignment: .topTrailing) {
                    if hover {
                        Button { editing = true } label: {
                            Image(systemName: "pencil")
                                .font(.dsIcon(11, .medium))
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

/// A seamless, auto-growing text area: no chrome until hovered or focused.
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
            // TextEditor's intrinsic height counts newlines, not wrapped lines; an invisible Text with the same metrics sets the real height.
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
            // Clicking away closes the editor; the text was already saved per keystroke.
            if !isFocused, focusNow { onDone() }
        }
        .animation(.easeOut(duration: 0.12), value: focused)
        .animation(.easeOut(duration: 0.12), value: hover)
    }
}


/// A turn's speaker name: click to edit; Return (or clicking away) saves to the job, Escape cancels.
private struct SpeakerName: View {
    let turn: TranscriptTurn
    @ObservedObject var model: NoteViewModel
    @Binding var editingLabel: String?
    @Binding var draft: String

    @FocusState private var focused: Bool
    @State private var hover = false
    /// The pointer is over the completion list: losing focus to a click there is a pick, not a commit.
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
                        RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous).fill(DS.surface)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
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

    /// The calendar's invitees not yet used on another speaker, narrowed by what is typed.
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
            .background(RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous).fill(DS.surface))
            .overlay(
                RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
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


/// Initials in a tinted circle; the tint is a stable function of the name (same palette and hash as the web).
struct SpeakerAvatar: View {
    let name: String

    private var tint: Color { DS.speakerTint(name) }

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

/// A speaker name in a text-only transcript: click to edit; Return rewrites every turn of that speaker in the note. Escape cancels.
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
                .background(RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous).fill(DS.surface))
                .overlay(RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
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

/// A small "?" on a turn's avatar: the attribution is a guess (overlapping speech).
struct UncertainMarker: View {
    static let explanation = "People talked over each other here."

    var body: some View {
        Text("?")
            .font(.dsIcon(9, .bold))
            .foregroundStyle(DS.inkText)
            .frame(width: 13, height: 13)
            .background(Circle().fill(DS.warn))
            .offset(x: 3, y: 3)
            .help(Self.explanation)
            .accessibilityLabel(Self.explanation)
    }
}


/// "[Musik 00:12–00:41]": music, silence or noise marked instead of transcribed. A line of its own, not a turn.
struct NoiseMarkerLine: View {
    let marker: TranscriptNoise
    let language: String?

    var body: some View {
        Text(marker.line(language: language))
            .font(.dsMeta)
            .italic()
            .foregroundStyle(DS.muted)
            .padding(.vertical, 2)
            .accessibilityLabel(marker.line(language: language))
    }
}


/// One row per unified spelling — Accept, Reject, Edit, Add to glossary. Read-only offline.
struct EntityReviewSheetView: View {
    @ObservedObject var model: NoteViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var editing: String?
    @State private var draft = ""
    @State private var learned: Set<String> = []

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Unified spellings").font(.dsMeta).bold()
            Text("One name, one spelling across the transcript, the note and its quotes. Nothing in the recording changes.")
                .font(.dsMeta).foregroundStyle(DS.muted)
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(model.entityCorrections.filter(\.needsReview)) { c in
                        row(c)
                        Divider()
                    }
                }
            }
            if !model.online {
                Text("Offline — reviewing needs a connection.").font(.dsMeta).foregroundStyle(DS.muted)
            }
            if let error = model.spellingError {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
            }
            HStack { Spacer(); Button("Done") { dismiss() } }
        }
        .padding(20)
        .frame(minWidth: 360, minHeight: 280)
        // The last spelling decided: nothing left to review.
        .onChange(of: model.entityCorrections) { _, corrections in
            if !corrections.contains(where: \.needsReview) { dismiss() }
        }
    }

    @ViewBuilder
    private func row(_ c: EntityCorrection) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                if editing == c.id {
                    TextField("Spelling", text: $draft)
                } else {
                    Text(c.toText).bold()
                }
                Text("\(c.isApplied ? "applied" : "proposed") · \(c.occurrencesCount)× · \(c.sourceLabel)")
                    .font(.dsMeta).foregroundStyle(DS.muted)
            }
            Text("replaces: \(c.fromForms.joined(separator: ", "))").font(.dsMeta).foregroundStyle(DS.muted)
            HStack(spacing: 6) {
                if editing == c.id {
                    Button("Save") {
                        let value = draft.trimmingCharacters(in: .whitespaces)
                        editing = nil
                        Task { await model.decide(c, accept: true, toText: value) }
                    }
                    .disabled(draft.trimmingCharacters(in: .whitespaces).isEmpty)
                    Button("Cancel") { editing = nil }
                } else {
                    if !c.isApplied {
                        Button("Accept") { Task { await model.decide(c, accept: true) } }
                    }
                    Button("Reject") { Task { await model.decide(c, accept: false) } }
                    Button("Edit") { draft = c.toText; editing = c.id }
                    if c.isApplied && c.source != "glossary" && !learned.contains(c.id) {
                        Button("Add to glossary") {
                            learned.insert(c.id)
                            Task { await model.rememberSpelling(c) }
                        }
                    }
                    if learned.contains(c.id) {
                        Text("in the glossary").font(.dsMeta).foregroundStyle(DS.muted)
                    }
                }
            }
            .disabled(!model.online)
        }
    }
}

extension EntityCorrection {
    /// The paragraph with each accepted spelling quietly underlined.
    static func underlined(_ paragraph: String, _ corrections: [EntityCorrection]) -> AttributedString {
        var out = AttributedString(paragraph)
        for c in corrections where c.isApplied && !c.toText.isEmpty {
            var search = out.startIndex..<out.endIndex
            while let range = out[search].range(of: c.toText) {
                let before = range.lowerBound == out.startIndex ? nil : out.characters[out.characters.index(before: range.lowerBound)]
                let after = range.upperBound == out.endIndex ? nil : out.characters[range.upperBound]
                if !(before?.isLetter ?? false), !(after?.isLetter ?? false) {
                    out[range].underlineStyle = Text.LineStyle(pattern: .dot)
                }
                search = range.upperBound..<out.endIndex
            }
        }
        return out
    }
}
