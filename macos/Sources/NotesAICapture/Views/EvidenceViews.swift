import AppKit
import SwiftUI

// The pieces the web's note page has around a generated note (Summary
// Engine v2 Q5, Sprint 36): the evidence behind a line, the names the
// engine respelled, what is still open from the last meeting, the client
// version, and the version history. Members only — none of this is ever
// rendered on the shared page, the client version or the PDF.

// MARK: - The evidence behind one line (Q5)

/// A certainty chip ("Forecast · Reinbold"), a corrected-name chip, and a
/// quiet mark that opens the quote the line rests on. Labels are data from
/// the row, drawn here — never words in the note a person would have to
/// edit around.
struct LineEvidenceView: View {
    @ObservedObject var model: NoteViewModel
    let row: GeneratedItem
    @State private var open = false

    var body: some View {
        HStack(spacing: 4) {
            if let chip = row.chipLabel {
                EvidenceChip(text: chip, tone: .neutral)
            }
            ForEach(row.respelled, id: \.surface) { c in
                EvidenceChip(text: c.canonical, tone: .accent)
                    .help("heard as: \(c.surface)")
            }
            Button {
                open.toggle()
            } label: {
                Image(systemName: "text.quote")
                    .font(.dsIcon(9, .semibold))
                    .foregroundStyle(open ? DS.accentText : DS.muted.opacity(0.7))
                    .frame(width: 18, height: 18)
                    .background(Circle().fill(open ? DS.accentSoft : .clear))
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .help("Show where this came from")
            .accessibilityLabel("Show where this came from")
            .popover(isPresented: $open, arrowEdge: .bottom) {
                EvidencePopover(model: model, row: row) { open = false }
            }
        }
        .fixedSize()
    }
}

private struct EvidenceChip: View {
    let text: String
    let tone: DSMetaPill.Tone

    var body: some View {
        Text(text)
            .font(.ds(10.5, .semibold))
            .foregroundStyle(tone == .accent ? DS.accentText : DS.text3)
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .background(Capsule().fill(tone == .accent ? DS.accentSoft : DS.surface2))
            .lineLimit(1)
    }
}

/// The quote (verbatim, as the transcriber heard it), when it was said and
/// by whom, a way to the transcript at that moment, and the other facts
/// the line rests on.
private struct EvidencePopover: View {
    @ObservedObject var model: NoteViewModel
    let row: GeneratedItem
    let close: () -> Void

    private var others: [String] { Array((row.cites ?? []).dropFirst()) }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let chip = row.chipLabel {
                EvidenceChip(text: chip, tone: .neutral)
            }
            Text("“\(row.quote)”")
                .font(.ds(13))
                .foregroundStyle(DS.text1)
                .lineSpacing(3)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 10) {
                Text(row.timeText + (row.speakerName.map { " · \($0)" } ?? ""))
                    .font(.dsMono(11))
                    .foregroundStyle(DS.muted)
                Spacer(minLength: 0)
                if model.canSeekTranscript {
                    Button("Show in transcript") {
                        close()
                        Task { await model.seekTranscript(to: row.startMs) }
                    }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 11.5, height: 24))
                }
            }
            if !others.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("and \(others.count) more:")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                    ForEach(others, id: \.self) { key in
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            Circle().fill(DS.muted).frame(width: 4, height: 4).offset(y: -1)
                            Text(model.rowsByKey[key]?.text ?? "another statement from the recording")
                                .font(.ds(12))
                                .foregroundStyle(DS.text2)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
        }
        .padding(14)
        .frame(width: 340, alignment: .leading)
        .background(DS.surface)
        .accessibilityLabel("Evidence")
    }
}

// MARK: - Names the engine respelled (Q5)

/// For the author to accept or reject. Accept: the name becomes a
/// workspace glossary term with the heard spelling as a mishearing — the
/// next generation spells it that way without asking anyone. Reject: the
/// line goes back to what the recording heard.
struct CorrectionsPanelView: View {
    @ObservedObject var model: NoteViewModel

    var body: some View {
        let corrections = model.corrections
        if !corrections.fixed.isEmpty || !corrections.doubted.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                DSLabel("Names in this note")
                ForEach(corrections.fixed) { c in
                    HStack(spacing: 8) {
                        (Text("heard ").foregroundColor(DS.muted)
                            + Text(c.surface)
                            + Text(" → ")
                            + Text(c.canonical).fontWeight(.semibold))
                            .font(.ds(13))
                            .foregroundStyle(DS.text1)
                        Spacer(minLength: 8)
                        if let done = model.correctionDone[c.id] {
                            Text(done)
                                .font(.dsMeta)
                                .foregroundStyle(DS.muted)
                        } else {
                            Button("Accept") { Task { await model.correct(c, accept: true) } }
                                .buttonStyle(DSButtonStyle(kind: .secondary, size: 11.5, height: 24))
                                .disabled(model.correctionBusy == c.id)
                            Button("Reject") { Task { await model.correct(c, accept: false) } }
                                .buttonStyle(DSButtonStyle(kind: .ghost, size: 11.5, height: 24))
                                .disabled(model.correctionBusy == c.id)
                        }
                    }
                }
                ForEach(corrections.doubted, id: \.self) { name in
                    (Text(name) + Text(" (?) — not sure of the spelling").foregroundColor(DS.muted))
                        .font(.ds(13))
                        .foregroundStyle(DS.text1)
                }
                if let error = model.correctionError {
                    DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill", text: error)
                }
            }
            .dsCard(padding: 14)
            .accessibilityLabel("Names in this note")
        }
    }
}

// MARK: - Still open from the last meeting (Sprint 36)

/// The previous meeting's unfinished business, at the top of this one.
/// The items keep the PREVIOUS note's key, so ticking one here does not
/// detach it from the meeting where it was agreed.
struct CarriedItemsView: View {
    @EnvironmentObject private var app: AppState
    @ObservedObject var model: NoteViewModel
    let readOnly: Bool

    var body: some View {
        let items = model.carriedItems
        if !items.isEmpty, let view = model.carried {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    DSLabel("Still open from \(view.fromDateText)")
                    if let source = view.fromNoteId {
                        Button(view.fromNoteCode ?? "that meeting") { app.openNote(source) }
                            .buttonStyle(.plain)
                            .font(.dsMono(10.5))
                            .foregroundStyle(DS.accentText)
                            .help("Open the meeting these came from")
                    }
                }
                ForEach(items) { item in
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Button {
                                Task { await model.setCarried(item, state: item.isDone ? "open" : "done_marked") }
                            } label: {
                                Image(systemName: item.isDone ? "checkmark.square.fill" : "square")
                                    .font(.dsIcon(14, .regular))
                                    .foregroundStyle(item.isDone ? DS.accent : DS.text3)
                            }
                            .buttonStyle(.plain)
                            .disabled(readOnly || model.carriedBusy == item.itemKey)
                            .accessibilityLabel(item.isDone ? "Reopen \(item.text)" : "Mark \(item.text) done")
                            (Text(item.ownerLabel.map { "\($0): " } ?? "").fontWeight(.semibold)
                                + Text(item.text)
                                + Text(item.dueText.map { " — \($0)" } ?? "").foregroundColor(DS.muted))
                                .font(.ds(13))
                                .foregroundStyle(item.isDone ? DS.muted : DS.text1)
                                .strikethrough(item.isDone, color: DS.muted)
                                .fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 8)
                            if !readOnly {
                                Button("Drop") { Task { await model.setCarried(item, state: "dropped") } }
                                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 11.5, height: 22))
                                    .disabled(model.carriedBusy == item.itemKey)
                                    .accessibilityLabel("Drop \(item.text)")
                            }
                        }
                        // The recording said it was done, and these are the words.
                        if item.state == "done_mentioned", let quote = item.doneQuote {
                            Text((item.doneSpeaker.map { "\($0): " } ?? "") + "“\(quote)”")
                                .font(.dsMeta)
                                .foregroundStyle(DS.muted)
                                .padding(.leading, 22)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
            .dsCard(padding: 14)
            .accessibilityLabel("Still open from the last meeting")
        }
    }
}

// MARK: - The client version (Sprint 36)

/// What this note looks like to someone outside the workspace. A preview
/// of the real thing, not a mock-up of it: the server builds it with the
/// same function the shared page and the client PDF use.
struct ClientVersionView: View {
    @ObservedObject var model: NoteViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if model.clientVersionLoading, model.clientVersion == nil {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Building the client version…")
                        .font(.dsBody)
                        .foregroundStyle(DS.muted)
                }
            } else if let error = model.clientVersionError {
                DSNotice(tone: .info, symbol: "info.circle", text: error)
            } else if let doc = model.clientVersion {
                Text("This is exactly what someone outside the workspace sees — on the shared page and in the PDF. Your own notes and the transcript are never part of it.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
                if let check = model.clientCheck, !check.warnings.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        DSLabel("Worth checking before you share")
                        ForEach(check.warnings) { w in
                            HStack(alignment: .firstTextBaseline, spacing: 8) {
                                Text("\(w.count)")
                                    .font(.dsMono(11))
                                    .foregroundStyle(DS.warn)
                                    .frame(minWidth: 16, alignment: .trailing)
                                Text(w.detail)
                                    .font(.ds(13))
                                    .foregroundStyle(DS.text1)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: DS.radius, style: .continuous).fill(DS.warnSoft))
                }
                if doc.sections.isEmpty {
                    DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill",
                             text: "There is nothing a client could read yet — every section is internal, empty, or the transcript.")
                } else {
                    VStack(alignment: .leading, spacing: 18) {
                        Text(doc.title.isEmpty ? "Untitled note" : doc.title)
                            .font(.dsDisplay(22))
                            .foregroundStyle(DS.text1)
                        ForEach(doc.sections) { section in
                            VStack(alignment: .leading, spacing: 6) {
                                if !section.name.isEmpty {
                                    Text(section.name)
                                        .font(.dsDisplay(16, .semibold))
                                        .foregroundStyle(DS.text1)
                                }
                                RichTextView(text: section.text, size: DS.docText - 1)
                            }
                        }
                    }
                    .dsCard(padding: 22, radius: DS.radiusXl)
                }
            }
        }
        .task(id: model.version) { await model.loadClientVersion() }
    }
}

// MARK: - History

/// The versions of this note, newest first; one opens read-only.
struct HistoryPanel: View {
    @ObservedObject var model: NoteViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                DSLabel("History")
                Spacer()
                if model.historyLoading { ProgressView().controlSize(.mini) }
            }
            if let versions = model.history {
                if versions.isEmpty {
                    Text("No earlier versions yet.")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                }
                ForEach(versions.sorted { $0.versionNumber > $1.versionNumber }) { v in
                    let current = v.versionNumber == model.version && model.viewing == nil
                    let reading = model.viewing?.versionNumber == v.versionNumber
                    Button {
                        if v.versionNumber == model.version {
                            model.backToCurrent()
                        } else {
                            Task { await model.view(version: v.versionNumber) }
                        }
                    } label: {
                        HStack(spacing: 8) {
                            Text("v\(v.versionNumber)")
                                .font(.dsMono(11))
                                .foregroundStyle(reading || current ? DS.accentText : DS.text3)
                                .frame(width: 34, alignment: .leading)
                            Text(formatDateTime(v.createdAt))
                                .font(.ds(12.5))
                                .foregroundStyle(DS.text1)
                            if v.isAmendment, let kind = v.amendmentType {
                                DSChip(text: kind.capitalized, tint: DS.indigo, soft: DS.indigoSoft)
                            }
                            if let reason = v.amendmentReason, !reason.isEmpty {
                                Text(reason)
                                    .font(.dsMeta)
                                    .foregroundStyle(DS.muted)
                                    .lineLimit(1)
                            }
                            Spacer(minLength: 4)
                            if current {
                                Text("Current")
                                    .font(.dsMeta)
                                    .foregroundStyle(DS.muted)
                            }
                        }
                        .padding(.horizontal, 8)
                        .frame(height: 28)
                        .background(
                            RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                                .fill(reading ? DS.accentSoft : .clear)
                        )
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .dsCard(padding: 12)
    }
}
