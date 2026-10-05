import SwiftUI

/// The evidence behind one generated line: the verbatim quote, when and by
/// whom, the other statements, a way to the transcript. Members only.
struct EvidenceSheet: View {
    @ObservedObject var model: NoteViewModel
    let row: GeneratedItem
    let onClose: () -> Void

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 6) {
                        if let chip = row.chipLabel {
                            DSChip(text: chip, tint: DS.text3, soft: DS.surface2)
                        }
                        ForEach(row.correctedNames, id: \.self) { name in
                            DSChip(text: name, tint: DS.accentText, soft: DS.accentSoft)
                        }
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        Text("“\(row.quote)”")
                            .font(.ds(17))
                            .foregroundStyle(DS.text1)
                            .lineSpacing(3)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                        Text(meta)
                            .font(.dsMeta)
                            .foregroundStyle(DS.muted)
                    }
                    .dsCard()
                    if model.canSeekTranscript {
                        Button {
                            Task { await model.showInTranscript(row) }
                        } label: {
                            Label("Show in transcript", systemImage: "text.quote")
                        }
                        .buttonStyle(DSButtonStyle(kind: .secondary, size: 15, height: 40, fill: true))
                    }
                    let others = model.supportingRows(of: row)
                    if !others.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            DSLabel("And \(others.count) more")
                            ForEach(others) { other in
                                HStack(alignment: .firstTextBaseline, spacing: 7) {
                                    Circle().fill(DS.muted).frame(width: 4, height: 4).offset(y: -1)
                                    Text(other.text)
                                        .font(.ds(15))
                                        .foregroundStyle(DS.text2)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                        }
                        .dsCard()
                    }
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(DS.bg)
            .navigationTitle("Where this came from")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) { Button("Done", action: onClose) }
            }
        }
    }

    private var meta: String {
        var parts = [formatElapsed(ms: row.startMs)]
        if let speaker = row.speakerName, !speaker.isEmpty { parts.append(speaker) }
        return parts.joined(separator: " · ")
    }
}

/// Short / Standard / Detailed. A view — never an edit, never a model call.
struct DetailToggle: View {
    @ObservedObject var model: NoteViewModel

    var body: some View {
        DSSegmentedPill(
            options: [
                .init(NoteViewModel.DetailLevel.short, label: "Short", help: "Only the overview"),
                .init(.standard, label: "Standard", help: "The note as written"),
                .init(.detailed, label: "Detailed", help: "Plus everything else that was said"),
            ],
            selection: $model.detail, height: 32)
        .accessibilityLabel("How much to show")
    }
}

/// Names the engine respelled, for the author to accept (glossary term) or reject (back to what was heard).
struct CorrectionsPanel: View {
    @ObservedObject var model: NoteViewModel

    var body: some View {
        let fixed = model.nameCorrections
        let doubted = model.doubtedNames
        if !fixed.isEmpty || !doubted.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                Text("Names in this note")
                    .font(.dsDisplay(18, .semibold))
                    .foregroundStyle(DS.text1)
                VStack(spacing: 0) {
                    ForEach(fixed) { fix in
                        row(fix)
                        if fix.id != fixed.last?.id || !doubted.isEmpty { DSDivider() }
                    }
                    ForEach(doubted, id: \.self) { name in
                        HStack(spacing: 6) {
                            Text(name)
                                .font(.ds(15, .medium))
                                .foregroundStyle(DS.text1)
                            Text("(?) — not sure of the spelling")
                                .font(.dsMeta)
                                .foregroundStyle(DS.muted)
                            Spacer(minLength: 0)
                        }
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        if name != doubted.last { DSDivider() }
                    }
                }
                .dsCard(padding: 0)
                if let error = model.correctionError {
                    DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill", text: error)
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityLabel("Names in this note")
        }
    }

    private func row(_ fix: NoteViewModel.NameCorrection) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 4) {
                Text("heard").font(.dsMeta).foregroundStyle(DS.muted)
                Text(fix.surface).font(.ds(15)).foregroundStyle(DS.text2)
                Text("→").font(.dsMeta).foregroundStyle(DS.muted)
                Text(fix.canonical).font(.ds(15, .semibold)).foregroundStyle(DS.text1)
            }
            if let outcome = model.correctionOutcomes[fix.id] {
                Text(outcome).font(.dsMeta).foregroundStyle(DS.muted)
            } else {
                HStack(spacing: 8) {
                    Button("Accept") { Task { await model.act(on: fix, accept: true) } }
                        .buttonStyle(DSButtonStyle(kind: .secondary, size: 13, height: 30))
                    Button("Reject") { Task { await model.act(on: fix, accept: false) } }
                        .buttonStyle(DSButtonStyle(kind: .ghost, size: 13, height: 30))
                    if model.correctionBusy == fix.id { ProgressView().controlSize(.small) }
                }
                .disabled(model.correctionBusy != nil || !model.editable)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }
}
