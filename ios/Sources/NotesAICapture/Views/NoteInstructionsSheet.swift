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
    private var blocked: Bool { working || !model.online }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Instructions for this note only. They are added to the workspace's instructions and the note is written again.")
                        .font(.dsMeta).foregroundStyle(DS.muted)
                        .fixedSize(horizontal: false, vertical: true)
                    TextEditor(text: $draft)
                        .font(.system(size: 15 - 2, design: .monospaced))
                        .foregroundStyle(DS.text1)
                        .scrollContentBackground(.hidden)
                        .frame(minHeight: 180)
                        .padding(8)
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
                    HStack(spacing: 8) {
                        Button("Check") { Task { await check() } }
                            .buttonStyle(DSButtonStyle(kind: .secondary))
                            .disabled(blocked || tooLong || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        Button("Save and rewrite") { Task { await rewrite(draft) } }
                            .buttonStyle(DSButtonStyle(kind: .primary))
                            .disabled(blocked || tooLong || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        if hasInstructions {
                            Button("Remove and rewrite") { Task { await rewrite(nil) } }
                                .buttonStyle(DSButtonStyle(kind: .ghost))
                                .disabled(blocked)
                        }
                    }
                    if working { ProgressView() }
                    if let error {
                        DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                    }
                    if let notice {
                        DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill", text: notice)
                    }
                    if let preview { readout(preview) }
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(DS.bg)
            .navigationTitle("Write this note differently")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel", action: onClose)
                }
            }
        }
        .onAppear { draft = current?.text ?? "" }
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
        Text(text).font(.ds(15 - 2, .semibold)).foregroundStyle(DS.text1).padding(.top, 4)
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
