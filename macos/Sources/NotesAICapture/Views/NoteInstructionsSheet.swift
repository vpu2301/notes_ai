import SwiftUI

/// "Write this note differently…" (N4): instructions for this note only, added to the
/// workspace's, then the note is written again.
struct NoteInstructionsSheet: View {
    @ObservedObject var model: NoteViewModel
    let onClose: () -> Void

    @State private var draft = ""
    @State private var preview: AIInstructions?
    @State private var working = false
    @State private var error: String?
    @State private var notice: String?

    private var current: AIInstructions? { model.noteInstructions }
    private var hasInstructions: Bool { (current?.version ?? 0) > 0 }
    private var maxChars: Int { current?.maxChars ?? 8000 }
    private var tooLong: Bool { draft.count > maxChars }
    private var blank: Bool { draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    private var blocked: Bool { working || !model.online }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            DSDivider()
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    TextEditor(text: $draft)
                        .font(.system(size: 13 - 2, design: .monospaced))
                        .foregroundStyle(DS.text1)
                        .scrollContentBackground(.hidden)
                        .frame(minHeight: 180)
                        .padding(6)
                        .background(
                            RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                                .strokeBorder(DS.line, lineWidth: DS.hairline)
                        )
                        .onChange(of: draft) { _, _ in preview = nil }
                    HStack {
                        if !model.online {
                            Text("Needs a connection").font(.dsMeta).foregroundStyle(DS.muted)
                        }
                        Spacer()
                        Text("\(draft.count) / \(maxChars)")
                            .font(.dsMeta)
                            .foregroundStyle(draft.count > maxChars - 200 ? DS.warn : DS.muted)
                    }
                    if let error {
                        DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                    }
                    if let notice {
                        DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill", text: notice)
                    }
                    if let preview { readout(preview) }
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            DSDivider()
            footer
        }
        .frame(width: 520, height: 520)
        .background(DS.bg)
        .onAppear { draft = current?.text ?? "" }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Write this note differently")
                .font(.dsDisplay(17, .medium))
                .foregroundStyle(DS.text1)
            Text("Instructions for this note only. They are added to the workspace's instructions and the note is written again.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
    }

    private var footer: some View {
        HStack(spacing: 10) {
            if hasInstructions {
                Button("Remove and rewrite") { Task { await rewrite(nil) } }
                    .buttonStyle(DSButtonStyle(kind: .ghost, height: 28))
                    .disabled(blocked)
            }
            Spacer(minLength: 8)
            if working { ProgressView().controlSize(.small) }
            Button("Cancel", action: onClose)
                .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                .keyboardShortcut(.cancelAction)
            Button("Check") { Task { await check() } }
                .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                .disabled(blocked || tooLong || blank)
            Button("Save and rewrite") { Task { await rewrite(draft) } }
                .buttonStyle(DSButtonStyle(kind: .primary, height: 28))
                .disabled(blocked || tooLong || blank)
                .keyboardShortcut(.defaultAction)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
    }

    /// What the writer took from the text, as the Data & AI card shows it.
    private func readout(_ i: AIInstructions) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if i.compileStatus == "failed" {
                DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill",
                         text: AIInstructions.failedText)
            }
            if !i.understood.isEmpty {
                heading("Understood")
                bullets(i.understood)
            }
            if !i.guidance.isEmpty {
                heading("Also passed to the writer as wording guidance")
                bullets(i.guidance)
            }
            if !i.notApplied.isEmpty {
                heading("Not applied")
                bullets(i.notApplied.map { "“\($0.text)” — \($0.message)" })
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .dsCard()
    }

    private func heading(_ text: String) -> some View {
        Text(text).font(.ds(13 - 2, .semibold)).foregroundStyle(DS.text1).padding(.top, 4)
    }

    private func bullets(_ lines: [String]) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text("•").foregroundStyle(DS.muted)
                    Text(line).fixedSize(horizontal: false, vertical: true)
                }
                .font(.dsMeta).foregroundStyle(DS.text2)
            }
        }
    }

    private func check() async {
        working = true
        error = nil
        defer { working = false }
        do {
            preview = try await model.previewNoteInstructions(draft)
        } catch {
            self.error = AuthCopy.message(for: error)
        }
    }

    /// nil removes the instructions. Closes on success; a refused rewrite keeps the sheet open to say so.
    private func rewrite(_ text: String?) async {
        working = true
        error = nil
        notice = nil
        defer { working = false }
        do {
            if let refused = try await model.rewriteWithInstructions(text) {
                notice = refused
            } else {
                onClose()
            }
        } catch {
            self.error = AuthCopy.message(for: error)
        }
    }
}
