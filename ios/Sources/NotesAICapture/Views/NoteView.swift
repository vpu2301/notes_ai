import SwiftUI
import UIKit

/// The note as a document, as the web editor shows it; autosaves until cancelled.
struct NoteView: View {
    @EnvironmentObject private var app: AppState
    @StateObject private var model: NoteViewModel
    @State private var confirmDelete = false
    @State private var shareByEmail = false
    @State private var shareWithClient = false
    @State private var historyPresented = false
    /// Which speaker label is being renamed, and the name it starts from.
    @State private var renaming: SpeakerRename?
    /// The turn whose avatar was tapped ("Move this turn to").
    @State private var movingTurn: TranscriptTurn?
    @State private var copied = false
    @State private var reviewingSpellings = false
    /// Which section is open in its editor; only one at a time.
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
                if model.tab == .transcript, model.canMoveTurns, model.online || model.selecting {
                    // Pick several turns, then move them at once.
                    Button(model.selecting ? "Done" : "Select") {
                        if model.selecting { model.endSelection() } else { model.selecting = true }
                    }
                    .disabled(!model.selecting && !model.canEditSpeakers)
                    .accessibilityHint(model.selecting ? "Ends picking turns" : "Pick several turns to move them together")
                }
                DSMenu(items: menuItems)
            }
        }
        .onChange(of: model.tab) { _, tab in
            if tab != .transcript { model.endSelection() }
        }
        .onChange(of: model.online) { _, online in
            if !online { model.endSelection() }
        }
        .task(id: model.noteId) { await model.load() }
        .task(id: model.noteId) { await model.loadSharing() }
        .onChange(of: model.note?.title) { old, title in
            // The server's name for the note replaces this device's placeholder.
            guard let title, !title.isEmpty else { return }
            if let jobId = capture?.jobId { app.updateRecent(jobId: jobId, title: title) }
            if old != nil, old != title { Task { await app.refreshNotes() } }
        }
        .task(id: model.version) { await model.loadItems() }
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
        .sheet(isPresented: $shareWithClient) {
            ShareWithClientSheet(model: model, webAppURL: app.settings.webAppURL) { url in
                // Hand the link straight to Mail / Messages / WhatsApp.
                shareWithClient = false
                model.shareItem = NoteViewModel.ShareItem(url: url)
            } onClose: { shareWithClient = false }
        }
        .sheet(isPresented: $shareByEmail) {
            ShareEmailSheet(
                noteTitle: model.content?.title ?? "",
                send: { recipients, message in
                    await model.sendShareEmail(recipients: recipients, message: message)
                },
                onClose: { shareByEmail = false })
        }
        .sheet(item: $renaming) { rename in
            SpeakerNameSheet(model: model, label: rename.label, initial: rename.initial)
                .presentationDetents([.medium, .large])
        }
        .sheet(isPresented: $historyPresented) {
            HistorySheet(model: model) { historyPresented = false }
                .presentationDetents([.medium, .large])
        }
        .sheet(item: $model.evidenceRow) { row in
            EvidenceSheet(model: model, row: row) { model.evidenceRow = nil }
                .presentationDetents([.medium, .large])
        }
        .confirmationDialog("Move this turn to", isPresented: Binding(
            get: { movingTurn != nil },
            set: { if !$0 { movingTurn = nil } }
        ), titleVisibility: .visible, presenting: movingTurn) { turn in
            moveButtons(for: [turn])
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
            if let note = model.note, note.status == .cancelled {
                DSChip(text: note.status.label, tint: note.status.tint, soft: note.status.soft)
            }
            if let viewing = model.viewing {
                DSChip(text: "Version \(viewing.versionNumber)", tint: DS.info, soft: DS.infoSoft)
            } else if model.conflict {
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
            // One entry: colleague vs outsider is the server's problem.
            .item("Send by email…", symbol: "envelope", disabled: model.busy || !canManage) {
                shareByEmail = true
            },
        ]
        if model.rules.externalLinksEnabled {
            // One link per recipient; hidden, not disabled, when the admin switched it off.
            items.insert(.item("Share with client…", symbol: "paperplane", disabled: model.busy || !canManage) {
                shareWithClient = true
            }, at: 3)
        }
        if hasLink && canManage {
            items.append(.item("Turn off public link", symbol: "globe.badge.chevron.backward",
                               disabled: model.busy) {
                Task { await model.revokePublicLink() }
            })
        }
        items.append(.separator)
        items.append(.item(model.viewing == nil ? "History" : "Back to current", symbol: "clock.arrow.circlepath") {
            if model.viewing == nil { historyPresented = true } else { model.backToCurrent() }
        })
        items.append(.item("Share PDF", symbol: "arrow.down.doc", disabled: model.busy) {
            Task { await model.exportPDF() }
        })
        items.append(.item("Share Markdown", symbol: "doc.plaintext", disabled: model.busy) {
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
                    get: { model.shownContent?.title ?? "" },
                    set: { model.setTitle($0) }
                ), axis: .vertical)
                .textFieldStyle(.plain)
                .font(.dsSerif(32))
                .tracking(-0.6)
                .foregroundStyle(DS.text1)
                .disabled(!model.editable)
                .padding(.bottom, 6)

                // Meta line: unframed facts, only the space is a control; scrolls sideways.
                if let note = model.note {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 2) {
                            DSMetaPill(symbol: "calendar", text: formatDateTime(note.createdAt))
                            DSMetaPill(text: "Updated \(relativeTime(note.updatedAt))")
                            if let template = model.templateName {
                                DSMetaPill(symbol: "sparkles", text: template, tone: .accent)
                            }
                            spacePill
                            DSMetaPill(text: note.code, mono: true)
                        }
                        .padding(.horizontal, DS.gutter - 8)
                    }
                    .padding(.horizontal, -DS.gutter)
                    .padding(.bottom, 14)
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

                RememberTermBanner(model: model)
                    .padding(.bottom, model.rememberOffer == nil ? 0 : 16)

                if let viewing = model.viewing {
                    HStack(spacing: 10) {
                        Image(systemName: "clock.arrow.circlepath")
                            .font(.dsSymbol(13, .semibold))
                            .foregroundStyle(DS.info)
                        Text("Version \(viewing.versionNumber) from \(formatDateTime(viewing.createdAt)). Read only.")
                            .font(.ds(14))
                            .foregroundStyle(DS.text1)
                            .fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: 6)
                        Button("Back to current") { model.backToCurrent() }
                            .buttonStyle(DSButtonStyle(kind: .secondary, size: 13, height: 30))
                    }
                    .padding(12)
                    .background(RoundedRectangle(cornerRadius: DS.radius, style: .continuous).fill(DS.infoSoft))
                    .padding(.bottom, 16)
                }

                if capture?.status == .complete || model.hasTranscript {
                    DSSegmentedPill(
                        options: [
                            .init(NoteViewModel.Tab.notes, label: "Notes"),
                            .init(NoteViewModel.Tab.transcript, label: "Transcript"),
                            .init(NoteViewModel.Tab.client, label: "Client version"),
                        ],
                        selection: $model.tab, height: 36)
                    .padding(.bottom, 20)
                }

                switch model.tab {
                case .notes: sections
                case .transcript: transcript
                case .client: ClientVersionView(model: model)
                }

                if model.viewing == nil, !model.chat.isEmpty || model.asking || model.askError != nil {
                    askThread.padding(.top, 32)
                }
                Color.clear.frame(height: 1).id("ask-end")
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, DS.gutter)
            .padding(.top, 12)
            // Breathing room under the last line (the composer is a safe-area inset).
            .padding(.bottom, 24)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: model.chat.count) { _, _ in
                withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo("ask-end", anchor: .bottom) }
            }
            .onChange(of: model.asking) { _, asking in
                if asking { withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo("ask-end", anchor: .bottom) } }
            }
            // A suggestion's quote was tapped — show its turn.
            .onChange(of: model.revealedTurn) { _, reveal in
                guard let reveal else { return }
                withAnimation(.easeOut(duration: 0.25)) { proxy.scrollTo(reveal.turnId, anchor: .center) }
            }
        }
        // A short wash of the page ground so text never runs into the composer.
        .safeAreaInset(edge: .bottom, spacing: 0) {
            if model.selecting { moveBar } else if model.viewing == nil { askBar }
        }
    }

    // MARK: - Ask this note

    /// The thread: questions in a bubble on the right, answers typeset under a spark.
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
                            .font(.dsSymbol(14, .medium))
                            .foregroundStyle(DS.accentText)
                            .frame(width: 20)
                        // Typeset like the note.
                        RichTextView(text: message.text)
                    }
                }
            }
            if model.asking {
                HStack(spacing: 10) {
                    Image(systemName: "sparkles")
                        .font(.dsSymbol(14, .medium))
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

    /// The composer floating over the foot of the document: field on top, tool row underneath.
    private var askBar: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField("Ask about this note…", text: $askDraft, axis: .vertical)
                .textFieldStyle(.plain)
                .font(.ds(16))
                .foregroundStyle(DS.text1)
                .lineLimit(1...6)
                .focused($askFocused)
                .submitLabel(.send)
            HStack(spacing: 8) {
                HStack(spacing: 6) {
                    Image(systemName: "sparkles")
                        .font(.dsSymbol(13, .medium))
                        .foregroundStyle(DS.accentText)
                    Text("This note")
                        .font(.ds(14))
                        .foregroundStyle(DS.text3)
                }
                Spacer(minLength: 0)
                Button {
                    sendQuestion()
                } label: {
                    Image(systemName: "arrow.up")
                        .font(.dsSymbol(14, .semibold))
                        .foregroundStyle(DS.inkText)
                        .frame(width: 34, height: 34)
                        .background(
                            RoundedRectangle(cornerRadius: DS.radiusSm + 2, style: .continuous)
                                .fill(DS.ink)
                        )
                }
                .buttonStyle(.plain)
                .disabled(askEmpty)
                .opacity(askEmpty ? 0.35 : 1)
                .accessibilityLabel("Send")
            }
        }
        .padding(.top, 14)
        .padding(.leading, 16)
        .padding(.trailing, 10)
        .padding(.bottom, 10)
        .background(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .fill(DS.surface)
                .shadow(color: .black.opacity(askFocused ? 0.16 : 0.10), radius: askFocused ? 14 : 10, y: 6)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .strokeBorder(askFocused ? DS.lineHover : DS.line, lineWidth: DS.hairline)
        )
        .contentShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .onTapGesture { askFocused = true }
        .padding(.horizontal, DS.gutter)
        .padding(.bottom, 10)
        .padding(.top, 6)
        .background(
            LinearGradient(colors: [DS.bg.opacity(0), DS.bg], startPoint: .top, endPoint: .bottom)
                .allowsHitTesting(false)
        )
    }

    private var askEmpty: Bool {
        model.asking || askDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
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
            if !model.items.isEmpty, model.viewing == nil {
                // Action items as objects; the section text below stays the source.
                ActionItemsSection(model: model)
            }
            if model.viewing == nil {
                generationStatus
            }
            if model.isGenerated {
                // How much to show, the names the engine respelled.
                DetailToggle(model: model)
                CorrectionsPanel(model: model)
            }
            if model.viewing == nil {
                CarriedItemsView(model: model)
            }
            if model.sections.isEmpty {
                Text("This note's template has no sections.")
                    .font(.dsBody)
                    .foregroundStyle(DS.muted)
            }
            if shownBlocks.isEmpty, !model.sections.isEmpty {
                Text(model.hasTranscript
                     ? "No notes yet — the transcript is under the other tab."
                     : "Nothing here yet.")
                    .font(.dsBody)
                    .foregroundStyle(DS.muted)
            }
            noteBlocks
        }
    }

    /// Generate Summary lives here and nowhere else.
    @ViewBuilder
    private var generationStatus: some View {
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
                .buttonStyle(DSButtonStyle(kind: .primary, height: 40))
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
            VStack(alignment: .leading, spacing: 10) {
                DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill",
                         text: generation.wroteNothing
                             ? GenerationView.nothingWrittenText : generation.failureText)
                HStack(spacing: 8) {
                    if generation.needsProcessorAcknowledgement {
                        Button("Open Data & AI") { app.showDataAndAI() }
                            .buttonStyle(DSButtonStyle(kind: .secondary, height: 36))
                    }
                    if generation.errorKind != "budget_exceeded" {
                        Button("Try again") { Task { await model.generateSummary() } }
                            .buttonStyle(DSButtonStyle(kind: .secondary, height: 36))
                            .disabled(model.generating)
                    }
                }
            }
        }
        if let generation = model.generation, !generation.isLive {
            generationFacts(generation)
        }
        if let error = model.generationError {
            VStack(alignment: .leading, spacing: 10) {
                DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill", text: error)
                if model.generationNeedsAcknowledgement {
                    Button("Open Data & AI") { app.showDataAndAI() }
                        .buttonStyle(DSButtonStyle(kind: .secondary, height: 36))
                }
            }
        }
    }

    /// Short = overview only; Standard = as written; Detailed adds unused verified facts.
    private var shownBlocks: [NoteViewModel.NoteBlock] {
        let all = model.blocks
        return model.isGenerated && model.detail == .short ? all.filter { $0.key == "gen:overview" } : all
    }

    /// The evidence behind a line, when the engine wrote it and can prove it.
    private var lineExtra: ((String) -> RichLineExtra?)? {
        guard model.isGenerated else { return nil }
        return { raw in
            guard let row = model.row(forLine: raw) else { return nil }
            return RichLineExtra(chip: row.chipLabel, names: row.correctedNames) { model.evidenceRow = row }
        }
    }

    /// One block per section the note HAS, headed only when titled.
    private var noteBlocks: some View {
        let alsoSaid = model.alsoSaidBySection
        return ForEach(shownBlocks) { block in
            VStack(alignment: .leading, spacing: 7) {
                if let title = block.title, !title.isEmpty {
                    // No hanging "#" on a phone (the web drops it below 820px too).
                    Text(title)
                        .font(.dsSerif(21))
                        .tracking(-0.2)
                        .foregroundStyle(DS.text1)
                }
                if block.isFreeText {
                    SectionField(
                        text: Binding(
                            get: { model.shownContent?.section(block.key).text ?? "" },
                            set: { model.setSectionText(block.key, $0) }
                        ),
                        name: block.name,
                        placeholder: block.placeholder,
                        editable: model.editable,
                        editing: Binding(
                            get: { editingSection == block.key },
                            set: { editingSection = $0 ? block.key : nil }
                        ),
                        extra: lineExtra)
                } else {
                    // Structured fields are edited in the web app; read-only here.
                    RichTextView(text: model.shownContent?.section(block.key).text ?? "", extra: lineExtra)
                }
                if let rows = alsoSaid[block.key], !rows.isEmpty {
                    alsoSaidView(rows)
                }
            }
        }
    }

    /// "Also said" — the verified facts no line used, with their evidence.
    private func alsoSaidView(_ rows: [GeneratedItem]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Also said")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
            ForEach(rows) { row in
                HStack(alignment: .firstTextBaseline, spacing: 7) {
                    Circle().fill(DS.muted).frame(width: 4, height: 4).offset(y: -1).frame(width: 14, alignment: .leading)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(row.text)
                            .font(.ds(16))
                            .foregroundStyle(DS.text2)
                            .lineSpacing(3)
                            .fixedSize(horizontal: false, vertical: true)
                        RichLineExtraView(extra: RichLineExtra(chip: row.chipLabel, names: row.correctedNames) {
                            model.evidenceRow = row
                        })
                    }
                }
            }
        }
        .padding(.top, 4)
    }

    /// The "filed in" pill: names the space, or offers the list.
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

    // MARK: - What the engine made of the recording (Q3)

    /// What the recording was taken to be, and the passages left out; each range opens the transcript.
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

    /// Speech that did not make it into the transcript, and why; a range inside the recording opens it there.
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
                                Button {
                                    renaming = SpeakerRename(label: speaker, initial: speaker)
                                } label: {
                                    HStack(spacing: 4) {
                                        Text(speaker)
                                            .font(.dsDisplay(15, .semibold))
                                            .foregroundStyle(DS.text1)
                                        Image(systemName: "pencil")
                                            .font(.dsSymbol(10, .medium))
                                            .foregroundStyle(DS.muted)
                                    }
                                }
                                .buttonStyle(.plain)
                                .accessibilityHint("Rename this speaker")
                            } else {
                                Text(unknownSpeakerName)
                                    .font(.dsDisplay(15, .semibold))
                                    .italic()
                                    .foregroundStyle(DS.muted)
                            }
                            Text(turn.text)
                                .font(.dsBody)
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
                        renaming = SpeakerRename(label: label, initial: model.name(for: label))
                    }
                }
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
                            Text(EntityCorrection.underlined(paragraph, model.entityCorrections))
                                .font(.dsBody)
                                .foregroundStyle(DS.text1)
                                .lineSpacing(3)
                                .textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    }
                    .padding(model.selecting || model.highlightedTurnId == turn.id ? 6 : 0)
                    .background(
                        RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                            .fill(turnTint(turn))
                    )
                    .contentShape(Rectangle())
                    .onTapGesture {
                        if model.selecting { model.toggleSelection(turn) }
                    }
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

    /// A turn's speaker name; a tap asks for a new one.
    @ViewBuilder
    private func speakerName(_ turn: TranscriptTurn) -> some View {
        if let label = turn.speaker {
            Button {
                renaming = SpeakerRename(label: label, initial: model.displayName(for: turn))
            } label: {
                HStack(spacing: 4) {
                    Text(model.displayName(for: turn))
                        .font(.dsDisplay(15, .semibold))
                        .foregroundStyle(DS.text1)
                    Image(systemName: "pencil")
                        .font(.dsSymbol(10, .medium))
                        .foregroundStyle(DS.muted)
                }
            }
            .buttonStyle(.plain)
            .disabled(model.renamingSpeaker)
            .accessibilityHint("Rename this speaker")
        } else {
            Text(unknownSpeakerName)
                .font(.dsDisplay(15, .semibold))
                .italic()
                .foregroundStyle(DS.muted)
        }
    }

    /// The turn's avatar: a tap offers to move the turn; in Select mode it is the checkbox.
    @ViewBuilder
    private func turnAvatar(_ turn: TranscriptTurn) -> some View {
        if model.selecting {
            let picked = model.selectedTurnIds.contains(turn.id)
            Button { model.toggleSelection(turn) } label: {
                Image(systemName: picked ? "checkmark.circle.fill" : "circle")
                    .font(.dsSymbol(22, .regular))
                    .foregroundStyle(picked ? DS.accent : DS.muted)
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(.plain)
            .frame(minWidth: 44, minHeight: 44)
            .disabled(!model.canMove(turn))
            .accessibilityLabel("Turn at \(formatElapsed(ms: turn.startMs))")
            .accessibilityValue(picked ? "Selected" : "Not selected")
            .accessibilityAddTraits(picked ? .isSelected : [])
            .accessibilityHint("Picks this turn to move with others")
        } else if model.canMove(turn) {
            Button { movingTurn = turn } label: {
                SpeakerAvatar(name: model.displayName(for: turn))
                    .overlay(alignment: .bottomTrailing) {
                        if turn.isUncertain { UncertainMarker().accessibilityHidden(true) }
                    }
            }
            .buttonStyle(.plain)
            .disabled(!model.canEditSpeakers)
            .accessibilityLabel("Move this turn to another speaker")
            .accessibilityValue(turn.isUncertain ? UncertainMarker.explanation : "")
        } else {
            SpeakerAvatar(name: model.displayName(for: turn))
                .overlay(alignment: .bottomTrailing) {
                    if turn.isUncertain { UncertainMarker() }
                }
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
        if model.canAddSpeaker {
            Button("New speaker") { Task { await model.moveTurns(moving, to: .new) } }
        }
        if model.canMoveToUnknown(moving) {
            Button("Unknown") { Task { await model.moveTurns(moving, to: .unknown) } }
        }
    }

    /// Select mode's action bar: "Move N turns to ▸".
    private var moveBar: some View {
        HStack(spacing: 10) {
            Text(model.selectedTurnIds.isEmpty ? "Tap turns to select them" : "\(model.selectedTurnIds.count) selected")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 8)
            Menu {
                moveButtons(for: model.selectedTurns)
            } label: {
                HStack(spacing: 4) {
                    Text(model.moveSelectionTitle)
                    Image(systemName: "chevron.right")
                }
                .font(.ds(14, .semibold))
            }
            .disabled(model.selectedTurnIds.isEmpty || !model.canEditSpeakers)
            .accessibilityHint("Choose the speaker these turns belong to")
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Selected turns")
        .padding(.horizontal, DS.gutter)
        .padding(.vertical, 12)
        .background(DS.bg)
        .overlay(alignment: .top) { DSDivider() }
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

/// One free-text section: typeset to read, tap to edit its markdown source;
/// an empty section goes straight to the editor.
private struct SectionField: View {
    @Binding var text: String
    let name: String
    let placeholder: String
    let editable: Bool
    @Binding var editing: Bool
    /// The evidence behind a line; nil when the engine did not write it.
    var extra: ((String) -> RichLineExtra?)? = nil

    var body: some View {
        if !editable {
            RichTextView(text: text, extra: extra)
        } else if editing || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            SectionEditor(text: $text, placeholder: placeholder, editable: true, focusNow: editing) {
                editing = false
            }
        } else {
            RichTextView(text: text, extra: extra)
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
                // Dismissing the keyboard closes the editor; text was saved per keystroke.
                if !isFocused, focusNow { onDone() }
            }
            .animation(.easeOut(duration: 0.12), value: focused)
    }
}


/// Initials in a tinted circle; the tint is a stable hash of the name (same as the web).
struct SpeakerAvatar: View {
    let name: String

    private var tint: Color {
        let h = name.unicodeScalars.reduce(0) { ($0 + Int($1.value)) % DS.speakerTints.count }
        return DS.speakerTints[h]
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

/// A small "?" on a turn's avatar — the attribution is a guess.
struct UncertainMarker: View {
    static let explanation = "People talked over each other here."

    var body: some View {
        Text("?")
            .font(.dsSymbol(9, .bold))
            .foregroundStyle(DS.inkText)
            .frame(width: 13, height: 13)
            .background(Circle().fill(DS.warn))
            .offset(x: 3, y: 3)
            .accessibilityLabel(Self.explanation)
    }
}

/// The speaker being renamed and the name the sheet starts from.
struct SpeakerRename: Identifiable {
    let label: String
    let initial: String
    var id: String { label }
}


/// "[Musik 00:12–00:41]" — a marked no-speech stretch, a line of its own.
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
