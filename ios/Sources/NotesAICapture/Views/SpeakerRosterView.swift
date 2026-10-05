import SwiftUI

/// The transcript's speakers: one chip per speaker with its talk share. A
/// tap asks rename or merge; a speaker who barely spoke gets one question
/// ("same person as someone else?"); a merge can be undone for 10 s.
/// Sprint 29: "Wrong number of speakers?" re-runs the separation for a
/// count the person gives, and a low-confidence count asks first — in
/// place of the small-speaker question, never beside it.
/// Sprint 30: the ⋯ menu resets every merge and moved turn (confirmed
/// first); a move refused because the speakers changed elsewhere says so.
/// Sprint 32: a name the server heard ("Hi, this is Anna") is offered
/// under the chips with its evidence; an older labelling offers a re-label;
/// every control has a VoiceOver name and grows with Dynamic Type.
struct SpeakerRosterView: View {
    @ObservedObject var model: NoteViewModel
    let onRename: (String) -> Void

    @State private var chosen: String?
    @State private var pickingCount = false
    @State private var confirmReset = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if model.showsRelabelBanner {
                VStack(alignment: .leading, spacing: 8) {
                    DSNotice(tone: .info, symbol: "wand.and.stars", text: NoteViewModel.relabelBannerText)
                    buttonRow {
                        Button("Re-label speakers") { Task { await model.relabelFromBanner() } }
                            .buttonStyle(DSButtonStyle(kind: .secondary, size: 13, height: 30))
                            .disabled(!model.online || model.renamingSpeaker)
                            .accessibilityHint("Tells the speakers apart again with the current method")
                        Button("Not now") { model.dismissRelabelBanner() }
                            .buttonStyle(DSButtonStyle(kind: .ghost, size: 13, height: 30))
                    }
                }
            } else if model.showsCountBanner {
                VStack(alignment: .leading, spacing: 8) {
                    DSNotice(tone: .info, symbol: "person.2.fill",
                             text: "We're not sure how many people spoke.")
                    buttonRow {
                        Button("Set number") { pickingCount = true }
                            .buttonStyle(DSButtonStyle(kind: .secondary, size: 13, height: 30))
                            .disabled(!model.online || model.renamingSpeaker)
                            .accessibilityHint("Say how many people spoke; speakers are told apart again")
                        Button("Looks right") { model.dismissCountBanner() }
                            .buttonStyle(DSButtonStyle(kind: .ghost, size: 13, height: 30))
                            .accessibilityHint("Stops asking for this recording")
                    }
                }
            } else if let prompt = model.smallSpeakerPrompt {
                VStack(alignment: .leading, spacing: 8) {
                    DSNotice(tone: .info, symbol: "person.2.fill",
                             text: "\(model.name(for: prompt.speaker.label)) spoke for \(spoke(prompt.speaker.speechMs)). Same person as someone else?")
                    buttonRow {
                        ForEach(prompt.targets, id: \.self) { target in
                            Button(model.name(for: target)) {
                                Task { await model.mergeSpeaker(from: prompt.speaker.label, into: target) }
                            }
                            .buttonStyle(DSButtonStyle(kind: .secondary, size: 13, height: 30))
                            .accessibilityLabel("Same person as \(model.name(for: target))")
                        }
                        Button("Keep") { model.keptSpeakers.insert(prompt.speaker.label) }
                            .buttonStyle(DSButtonStyle(kind: .ghost, size: 13, height: 30))
                            .accessibilityHint("Keeps them as a separate speaker")
                    }
                    .disabled(!model.online || model.renamingSpeaker)
                }
            }
            if let notice = model.speakerNotice {
                HStack(alignment: .top, spacing: 8) {
                    DSNotice(tone: .info, symbol: "arrow.triangle.2.circlepath", text: notice)
                    Button { model.speakerNotice = nil } label: {
                        Image(systemName: "xmark").font(.dsSymbol(11, .semibold))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(DS.muted)
                    .accessibilityLabel("Dismiss")
                }
            }
            HStack(spacing: 6) {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(model.speakers, id: \.self) { label in
                            Button { chosen = label } label: { chip(label) }
                                .buttonStyle(.plain)
                                .accessibilityLabel(model.speakerAccessibilityLabel(label))
                                .accessibilityHint("Rename or merge this speaker")
                            if model.isChannelNamed(label) {
                                // Sprint 31: a name from the microphone
                                // channel, not a person — one tap undoes it.
                                Button {
                                    Task { await model.clearChannelName(label) }
                                } label: {
                                    Image(systemName: "xmark")
                                        .font(.dsSymbol(10, .semibold))
                                        .frame(width: 28, height: 28)
                                        .frame(minWidth: 44, minHeight: 44)
                                        .contentShape(Rectangle())
                                }
                                .buttonStyle(.plain)
                                .foregroundStyle(DS.muted)
                                .accessibilityLabel(SpeakerChannelMarkers.removeLabel)
                                .disabled(!model.online || model.renamingSpeaker)
                            }
                        }
                    }
                }
                .disabled(model.relabel == .running)
                Menu {
                    Button("Reset speaker edits", role: .destructive) { confirmReset = true }
                        .disabled(!model.canResetSpeakerEdits || !model.canEditSpeakers)
                } label: {
                    Image(systemName: "ellipsis")
                        .font(.dsSymbol(14, .semibold))
                        .foregroundStyle(DS.muted)
                        .frame(width: 30, height: 30)
                        .frame(minWidth: 44, minHeight: 44)
                }
                .accessibilityLabel("Speaker options")
            }
            ForEach(model.speakers.compactMap(model.suggestion(for:))) { suggestion in
                NameSuggestionRow(model: model, suggestion: suggestion)
            }
            if let shortfall = model.hintShortfall {
                Text(shortfall)
                    .font(.dsMeta)
                    .foregroundStyle(DS.text2)
            }
            relabelStatus
            if let edit = model.lastEdit {
                HStack(spacing: 8) {
                    Text(edit.summary)
                        .font(.dsMeta)
                        .foregroundStyle(DS.text2)
                    Button("Undo") { Task { await model.undoLastSpeakerEdit() } }
                        .buttonStyle(DSButtonStyle(kind: .ghost, size: 13, height: 28))
                        .disabled(!model.online || model.renamingSpeaker)
                        .accessibilityLabel("Undo: \(edit.summary)")
                }
            }
            if model.online {
                if model.relabel != .running {
                    Button("Wrong number of speakers?") { pickingCount = true }
                        .buttonStyle(.plain)
                        .font(.dsMeta)
                        .foregroundStyle(DS.accentText)
                        .disabled(model.renamingSpeaker)
                }
            } else {
                Text("Connect to change speakers")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
            }
        }
        .onChange(of: model.announcement) { _, announcement in
            if let announcement { AccessibilityNotification.Announcement(announcement.text).post() }
        }
        .sheet(isPresented: $pickingCount) {
            SpeakerCountSheet(model: model)
                .presentationDetents([.medium])
        }
        .alert(NoteViewModel.resetConfirmTitle, isPresented: $confirmReset) {
            Button("Reset", role: .destructive) { Task { await model.resetSpeakerEdits() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(NoteViewModel.resetConfirmMessage)
        }
        .confirmationDialog(chosen.map { model.name(for: $0) } ?? "",
                            isPresented: Binding(get: { chosen != nil }, set: { if !$0 { chosen = nil } }),
                            titleVisibility: .visible) {
            if let label = chosen {
                Button("Rename…") { onRename(label) }
                if model.online {
                    ForEach(model.speakers.filter { $0 != label }, id: \.self) { other in
                        Button("Merge into \(model.name(for: other))") {
                            Task { await model.mergeSpeaker(from: label, into: other) }
                        }
                    }
                }
                if model.online, model.relabel != .running {
                    Button("Wrong number of speakers?") { pickingCount = true }
                }
            }
        }
    }

    /// The re-label in flight, its result, or its failure.
    @ViewBuilder
    private var relabelStatus: some View {
        switch model.relabel {
        case .idle:
            EmptyView()
        case .running:
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("Re-labelling speakers… the transcript stays readable")
                    .font(.dsMeta)
                    .foregroundStyle(DS.text2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .accessibilityElement(children: .combine)
        case .done(let count):
            HStack(spacing: 8) {
                Text("Now \(count) \(count == 1 ? "speaker" : "speakers")")
                    .font(.dsMeta)
                    .foregroundStyle(DS.text2)
                if model.canUndoRelabel {
                    Button("Undo") { Task { await model.undoRelabel() } }
                        .buttonStyle(DSButtonStyle(kind: .ghost, size: 13, height: 28))
                        .disabled(!model.online || model.renamingSpeaker)
                        .accessibilityLabel("Undo re-label")
                }
                Spacer(minLength: 0)
                Button { model.dismissRelabelResult() } label: {
                    Image(systemName: "xmark").font(.dsSymbol(11, .semibold))
                }
                .buttonStyle(.plain)
                .foregroundStyle(DS.muted)
                .accessibilityLabel("Dismiss")
            }
        case .failed:
            HStack(spacing: 8) {
                Text("Couldn't re-label speakers")
                    .font(.dsMeta)
                    .foregroundStyle(DS.dangerText)
                Button("Try again") { Task { await model.retryRelabel() } }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 13, height: 28))
                    .disabled(!model.online || model.renamingSpeaker)
                    .accessibilityLabel("Try re-labelling again")
            }
        }
    }

    /// Buttons side by side, stacked once the text is too large to fit.
    private func buttonRow(@ViewBuilder _ content: () -> some View) -> some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) { content() }
            VStack(alignment: .leading, spacing: 8) { content() }
        }
    }

    private func chip(_ label: String) -> some View {
        let share = model.speakerStats.first { $0.label == label }?.share
        return HStack(spacing: 6) {
            SpeakerAvatar(name: model.name(for: label))
                .scaleEffect(0.8)
                .frame(width: 24, height: 24)
            if let side = model.side(for: label) {
                Image(systemName: side.symbol)
                    .font(.dsSymbol(11, .semibold))
                    .foregroundStyle(DS.muted)
                    .accessibilityLabel(side.accessibilityLabel)
            }
            Text(model.name(for: label))
                .font(.ds(13, .medium))
                .foregroundStyle(DS.text1)
            if model.isChannelNamed(label) {
                Text(SpeakerChannelMarkers.fromMicrophone)
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
            } else if model.isSuggestedName(label) {
                Text("· \(SpeakerChannelMarkers.suggested)")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
            }
            if let share {
                Text("\(Int((share * 100).rounded())) %")
                    .font(.dsMono(11))
                    .foregroundStyle(DS.muted)
            }
        }
        .padding(.leading, 3)
        .padding(.trailing, 10)
        .padding(.vertical, 3)
        .background(Capsule().strokeBorder(DS.text3.opacity(0.35), lineWidth: 1))
    }
}

/// Sprint 32 — `Probably **Anna Keller** — "Hi, this is Anna from Acme" ·
/// 00:14` → Accept / Dismiss. The quote is the evidence and is shown
/// before anything is accepted; tapping it scrolls to the turn it was said in.
struct NameSuggestionRow: View {
    @ObservedObject var model: NoteViewModel
    let suggestion: NameSuggestion
    @ScaledMetric(relativeTo: .caption) private var iconSize: CGFloat = 11

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Image(systemName: "sparkles")
                    .font(.system(size: iconSize, weight: .semibold))
                    .foregroundStyle(DS.accentText)
                    .accessibilityHidden(true)
                Text("\(model.name(for: suggestion.label)): probably \(Text(suggestion.name).fontWeight(.semibold))")
                    .font(.ds(14))
                    .foregroundStyle(DS.text1)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let quote = suggestion.quote, !quote.isEmpty {
                Button { model.revealTurn(for: suggestion) } label: {
                    quoteText(quote)
                        .font(.dsMeta)
                        .foregroundStyle(DS.text2)
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(model.suggestionAccessibilityLabel(suggestion))
                .accessibilityHint("Scrolls to where this was said")
            }
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 8) { actions }
                VStack(alignment: .leading, spacing: 8) { actions }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: DS.radius, style: .continuous).fill(DS.surface2))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Name suggestion for \(model.name(for: suggestion.label))")
    }

    @ViewBuilder
    private var actions: some View {
        Button("Accept") { Task { await model.accept(suggestion) } }
            .buttonStyle(DSButtonStyle(kind: .secondary, size: 13, height: 30))
            .disabled(!model.canEditSpeakers)
            .accessibilityLabel("Accept \(suggestion.name)")
            .accessibilityHint("Names \(model.name(for: suggestion.label)) \(suggestion.name)")
        Button("Dismiss") { Task { await model.dismiss(suggestion) } }
            .buttonStyle(DSButtonStyle(kind: .ghost, size: 13, height: 30))
            .disabled(!model.online || model.renamingSpeaker)
            .accessibilityLabel("Dismiss suggestion")
    }

    private func quoteText(_ quote: String) -> Text {
        if let time = NoteViewModel.suggestionTime(suggestion) {
            return Text("“\(quote)” · \(time)")
        }
        return Text("“\(quote)”")
    }
}

/// "7 s" under a minute, "3 min" above.
func spoke(_ ms: Int) -> String {
    let s = Int((Double(ms) / 1000).rounded())
    return s < 60 ? "\(s) s" : "\(Int((Double(s) / 60).rounded())) min"
}

/// "How many people spoke?" — a count from 1 to 8, then a re-run of the
/// speaker separation. Warns first when the re-run would throw away merges.
struct SpeakerCountSheet: View {
    @ObservedObject var model: NoteViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var count = 2

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 18) {
                Text("Speakers are told apart again for this number of people. The transcript stays readable meanwhile.")
                    .font(.ds(14))
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
                Stepper(value: $count, in: 1...8) {
                    Text("\(count) \(count == 1 ? "person" : "people")")
                        .font(.ds(16, .medium))
                        .foregroundStyle(DS.text1)
                        .monospacedDigit()
                }
                if let warning = model.relabelReplacesMerges {
                    DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill", text: warning)
                }
                Button("Re-label speakers") {
                    let expected = count
                    dismiss()
                    Task { await model.relabelSpeakers(expected: expected) }
                }
                .buttonStyle(DSButtonStyle(kind: .primary, height: DS.control, fill: true))
                .disabled(!model.online || model.renamingSpeaker || model.relabel == .running)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, DS.gutter)
            .padding(.vertical, 16)
            .background(DS.bg)
            .navigationTitle("How many people spoke?")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
        .onAppear { count = model.suggestedSpeakerCount }
    }
}

/// Sprint 30 — "Rename speaker" as a sheet: the calendar's invitees not
/// yet given to another speaker come first (one tap names the speaker),
/// and typing a name is still there underneath.
struct SpeakerNameSheet: View {
    @ObservedObject var model: NoteViewModel
    let label: String
    let initial: String
    @Environment(\.dismiss) private var dismiss
    @State private var draft = ""
    @FocusState private var focused: Bool

    private var suggestions: [String] {
        // A text-only transcript has no job and so no candidates.
        model.jobId == nil ? [] : model.nameSuggestions(for: label)
    }

    var body: some View {
        NavigationStack {
            Form {
                if !suggestions.isEmpty {
                    Section("Invited") {
                        ForEach(suggestions, id: \.self) { name in
                            Button {
                                save(name, picked: true)
                            } label: {
                                HStack(spacing: 10) {
                                    SpeakerAvatar(name: name)
                                    Text(name).foregroundStyle(DS.text1)
                                }
                            }
                        }
                    }
                }
                Section {
                    TextField("Name", text: $draft)
                        .focused($focused)
                        .submitLabel(.done)
                        .onSubmit { save(draft, picked: false) }
                } footer: {
                    Text(model.isDraft
                         ? "The name is used in the transcript and at the start of each turn in the note."
                         : "The name is used in the transcript; a cancelled note keeps its text.")
                }
            }
            .navigationTitle("Rename speaker")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Save") { save(draft, picked: false) }
                        .disabled(model.renamingSpeaker)
                }
            }
        }
        .onAppear {
            draft = initial
            if suggestions.isEmpty { focused = true }
        }
    }

    private func save(_ name: String, picked: Bool) {
        dismiss()
        Task { await model.renameSpeaker(label: label, to: name, picked: picked) }
    }
}
