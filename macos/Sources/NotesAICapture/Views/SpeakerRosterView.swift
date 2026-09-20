import SwiftUI

/// The transcript's speakers: one chip per speaker with its talk share and
/// a menu to rename or merge it. A speaker who barely spoke gets one
/// question ("same person as someone else?"); a merge can be undone for 10 s.
/// Sprint 29: "Wrong number of speakers?" re-runs the separation for a
/// count the person gives, and a low-confidence count asks first — in
/// place of the small-speaker question, never beside it.
/// Sprint 30: the ⋯ menu resets every merge and moved turn (confirmed
/// first); a move refused because the speakers changed elsewhere says so.
/// Sprint 32: a name the server heard ("Hi, this is Anna") is offered
/// under the chips with its evidence; an older labelling offers a re-label;
/// every control has a name for VoiceOver and a keyboard path.
struct SpeakerRosterView: View {
    @ObservedObject var model: NoteViewModel
    let onRename: (String) -> Void

    @State private var pickingCount = false
    @State private var confirmReset = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let notice = model.speakerNotice {
                HStack(spacing: 8) {
                    DSNotice(tone: .info, symbol: "arrow.triangle.2.circlepath", text: notice)
                    Button { model.speakerNotice = nil } label: {
                        Image(systemName: "xmark").font(.system(size: 10, weight: .semibold))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(DS.muted)
                    .help("Dismiss")
                    .accessibilityLabel("Dismiss")
                }
            }
            if model.showsRelabelBanner {
                HStack(spacing: 8) {
                    DSNotice(tone: .info, symbol: "wand.and.stars", text: NoteViewModel.relabelBannerText)
                    Button("Re-label") { Task { await model.relabelFromBanner() } }
                        .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
                        .disabled(!model.online || model.renamingSpeaker)
                        .accessibilityLabel("Re-label speakers")
                        .accessibilityHint("Tells the speakers apart again with the current method")
                    Button { model.dismissRelabelBanner() } label: {
                        Image(systemName: "xmark").font(.system(size: 10, weight: .semibold))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(DS.muted)
                    .help("Not now")
                    .accessibilityLabel("Not now")
                }
            } else if model.showsCountBanner {
                HStack(spacing: 8) {
                    DSNotice(tone: .info, symbol: "person.2.fill",
                             text: "We're not sure how many people spoke.")
                    Button("Set number") { pickingCount = true }
                        .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
                        .disabled(!model.online || model.renamingSpeaker)
                        .accessibilityHint("Say how many people spoke; speakers are told apart again")
                    Button("Looks right") { model.dismissCountBanner() }
                        .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 26))
                        .accessibilityHint("Stops asking for this recording")
                }
            } else if let prompt = model.smallSpeakerPrompt {
                HStack(spacing: 8) {
                    DSNotice(tone: .info, symbol: "person.2.fill",
                             text: "\(model.name(for: prompt.speaker.label)) spoke for \(spoke(prompt.speaker.speechMs)). Same person as someone else?")
                    ForEach(prompt.targets, id: \.self) { target in
                        Button(model.name(for: target)) {
                            Task { await model.mergeSpeaker(from: prompt.speaker.label, into: target) }
                        }
                        .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
                        .accessibilityLabel("Same person as \(model.name(for: target))")
                    }
                    Button("Keep") { model.keptSpeakers.insert(prompt.speaker.label) }
                        .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 26))
                        .accessibilityHint("Keeps them as a separate speaker")
                }
                .disabled(!model.online || model.renamingSpeaker)
            }
            HStack(spacing: 6) {
                ForEach(model.speakers, id: \.self) { label in
                    Menu {
                        Button("Rename…") { onRename(label) }
                        MergeMenu(model: model, label: label)
                        Divider()
                        Button("Wrong number of speakers?") { pickingCount = true }
                            .disabled(!model.online || model.relabel == .running)
                    } label: {
                        chip(label)
                    }
                    .menuStyle(.button)
                    .buttonStyle(.plain)
                    .menuIndicator(.hidden)
                    .fixedSize()
                    .help("Rename or merge this speaker")
                    .accessibilityLabel(model.speakerAccessibilityLabel(label))
                    .accessibilityHint("Opens a menu to rename or merge this speaker")
                    .disabled(model.relabel == .running)
                    if model.isChannelNamed(label) {
                        // Sprint 31: the name came from the microphone
                        // channel, not from a person — one click undoes it.
                        Button {
                            Task { await model.clearChannelName(label) }
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 9, weight: .semibold))
                                .frame(width: 16, height: 16)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(DS.muted)
                        .help(SpeakerChannelMarkers.removeLabel)
                        .accessibilityLabel(SpeakerChannelMarkers.removeLabel)
                        .disabled(!model.online || model.renamingSpeaker || model.relabel == .running)
                    }
                }
                Menu {
                    Button("Reset speaker edits…") { confirmReset = true }
                        .disabled(!model.canResetSpeakerEdits || !model.canEditSpeakers)
                } label: {
                    Image(systemName: "ellipsis")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(DS.muted)
                        .frame(width: 24, height: 24)
                        .contentShape(Rectangle())
                }
                .menuStyle(.button)
                .buttonStyle(.plain)
                .menuIndicator(.hidden)
                .fixedSize()
                .help("Speaker options")
                .accessibilityLabel("Speaker options")
                if let edit = model.lastEdit {
                    Text(edit.summary)
                        .font(.dsMeta)
                        .foregroundStyle(DS.text2)
                        .padding(.leading, 6)
                    Button("Undo") { Task { await model.undoLastSpeakerEdit() } }
                        .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 26))
                        .disabled(!model.online || model.renamingSpeaker)
                        .accessibilityLabel("Undo: \(edit.summary)")
                }
                if !model.online {
                    Text("Connect to change speakers")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                } else if model.relabel != .running {
                    Button("Wrong number of speakers?") { pickingCount = true }
                        .buttonStyle(.plain)
                        .font(.dsMeta)
                        .foregroundStyle(DS.accentText)
                        .padding(.leading, 6)
                        .disabled(model.renamingSpeaker)
                        .popover(isPresented: $pickingCount, arrowEdge: .bottom) {
                            SpeakerCountPopover(model: model) { pickingCount = false }
                        }
                }
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
        }
        .onChange(of: model.announcement) { _, announcement in
            if let announcement { AccessibilityNotification.Announcement(announcement.text).post() }
        }
        .alert(NoteViewModel.resetConfirmTitle, isPresented: $confirmReset) {
            Button("Reset", role: .destructive) { Task { await model.resetSpeakerEdits() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(NoteViewModel.resetConfirmMessage)
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
            }
            .accessibilityElement(children: .combine)
        case .done(let count):
            HStack(spacing: 8) {
                Text("Now \(count) \(count == 1 ? "speaker" : "speakers")")
                    .font(.dsMeta)
                    .foregroundStyle(DS.text2)
                if model.canUndoRelabel {
                    Button("Undo") { Task { await model.undoRelabel() } }
                        .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 26))
                        .disabled(!model.online || model.renamingSpeaker)
                        .accessibilityLabel("Undo re-label")
                }
                Button { model.dismissRelabelResult() } label: {
                    Image(systemName: "xmark").font(.system(size: 10, weight: .semibold))
                }
                .buttonStyle(.plain)
                .foregroundStyle(DS.muted)
                .help("Dismiss")
                .accessibilityLabel("Dismiss")
            }
        case .failed:
            HStack(spacing: 8) {
                Text("Couldn't re-label speakers")
                    .font(.dsMeta)
                    .foregroundStyle(DS.dangerText)
                Button("Try again") { Task { await model.retryRelabel() } }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 26))
                    .disabled(!model.online || model.renamingSpeaker)
                    .accessibilityLabel("Try re-labelling again")
            }
        }
    }

    private func chip(_ label: String) -> some View {
        let share = model.speakerStats.first { $0.label == label }?.share
        return HStack(spacing: 6) {
            SpeakerAvatar(name: model.name(for: label))
                .scaleEffect(0.8)
                .frame(width: 22, height: 22)
            if let side = model.side(for: label) {
                Image(systemName: side.symbol)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(DS.muted)
                    .help(side.accessibilityLabel)
                    .accessibilityLabel(side.accessibilityLabel)
            }
            Text(model.name(for: label))
                .font(.ds(12.5, .medium))
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
                    .font(.dsMono(10.5))
                    .foregroundStyle(DS.muted)
            }
        }
        .padding(.leading, 3)
        .padding(.trailing, 10)
        .padding(.vertical, 3)
        .background(Capsule().strokeBorder(DS.text3.opacity(0.35), lineWidth: 1))
        .contentShape(Capsule())
    }
}

/// Sprint 32 — `Probably **Anna Keller** — "Hi, this is Anna from Acme" ·
/// 00:14` → Accept / ✕. The quote is the evidence and is shown before
/// anything is accepted; clicking it scrolls to the turn it was said in.
struct NameSuggestionRow: View {
    @ObservedObject var model: NoteViewModel
    let suggestion: NameSuggestion

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: "sparkles")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(DS.accentText)
                .accessibilityHidden(true)
            Text("\(model.name(for: suggestion.label)): probably \(Text(suggestion.name).fontWeight(.semibold))")
                .font(.dsMeta)
                .foregroundStyle(DS.text1)
                .fixedSize()
            if let quote = suggestion.quote, !quote.isEmpty {
                Button { model.revealTurn(for: suggestion) } label: {
                    quoteText(quote)
                        .font(.dsMeta)
                        .foregroundStyle(DS.text2)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .buttonStyle(.plain)
                .help("Show where this was said")
                .accessibilityLabel(model.suggestionAccessibilityLabel(suggestion))
                .accessibilityHint("Scrolls to where this was said")
            }
            Button("Accept") { Task { await model.accept(suggestion) } }
                .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 24))
                .disabled(!model.canEditSpeakers)
                .accessibilityLabel("Accept \(suggestion.name)")
                .accessibilityHint("Names \(model.name(for: suggestion.label)) \(suggestion.name)")
            Button { Task { await model.dismiss(suggestion) } } label: {
                Image(systemName: "xmark").font(.system(size: 9, weight: .semibold))
                    .frame(width: 16, height: 16)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .foregroundStyle(DS.muted)
            .disabled(!model.online || model.renamingSpeaker)
            .help("Dismiss suggestion")
            .accessibilityLabel("Dismiss suggestion")
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Name suggestion for \(model.name(for: suggestion.label))")
    }

    private func quoteText(_ quote: String) -> Text {
        if let time = NoteViewModel.suggestionTime(suggestion) {
            return Text("“\(quote)” · \(time)")
        }
        return Text("“\(quote)”")
    }
}

/// "Merge into ▸" — the other speakers, earlier labels first so a merge
/// keeps the lower number.
struct MergeMenu: View {
    @ObservedObject var model: NoteViewModel
    let label: String

    var body: some View {
        Menu("Merge into") {
            ForEach(model.speakers.filter { $0 != label }, id: \.self) { other in
                Button(model.name(for: other)) {
                    Task { await model.mergeSpeaker(from: label, into: other) }
                }
            }
        }
        .disabled(!model.online || model.renamingSpeaker || model.speakers.count < 2)
    }
}

/// "7 s" under a minute, "3 min" above.
func spoke(_ ms: Int) -> String {
    let s = Int((Double(ms) / 1000).rounded())
    return s < 60 ? "\(s) s" : "\(Int((Double(s) / 60).rounded())) min"
}

/// "How many people spoke?" — a count from 1 to 8, then a re-run of the
/// speaker separation. Warns first when the re-run would throw away merges.
struct SpeakerCountPopover: View {
    @ObservedObject var model: NoteViewModel
    let onClose: () -> Void
    @State private var count = 2

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("How many people spoke?")
                .font(.ds(13, .semibold))
                .foregroundStyle(DS.text1)
            Stepper(value: $count, in: 1...8) {
                Text("\(count) \(count == 1 ? "person" : "people")")
                    .font(.ds(13, .medium))
                    .foregroundStyle(DS.text1)
                    .monospacedDigit()
            }
            Text("Speakers are told apart again for this number. The transcript stays readable meanwhile.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
            if let warning = model.relabelReplacesMerges {
                DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill", text: warning)
            }
            HStack {
                Spacer()
                Button("Cancel", action: onClose)
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 26))
                    .keyboardShortcut(.cancelAction)
                Button("Re-label speakers") {
                    let expected = count
                    onClose()
                    Task { await model.relabelSpeakers(expected: expected) }
                }
                .buttonStyle(DSButtonStyle(kind: .primary, size: 12, height: 26))
                .keyboardShortcut(.defaultAction)
                .disabled(!model.online || model.renamingSpeaker || model.relabel == .running)
            }
        }
        .padding(14)
        .frame(width: 280)
        .onAppear { count = model.suggestedSpeakerCount }
    }
}
