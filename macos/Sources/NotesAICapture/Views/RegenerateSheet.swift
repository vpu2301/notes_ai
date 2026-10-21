import SwiftUI

/// "Regenerate as…" (P2): choose the writer's template, then write the note again with it.
/// The choice sticks to the note. Any editor of a note with a recording.
struct RegenerateSheet: View {
    @ObservedObject var model: NoteViewModel
    let onClose: () -> Void

    @State private var template: NoteTemplate = .auto
    @State private var working = false
    @State private var error: String?
    @State private var notice: String?

    private var blocked: Bool { working || !model.online }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Regenerate this note")
                    .font(.dsDisplay(17, .medium))
                    .foregroundStyle(DS.text1)
                Text("The note is written again from its recording with the template you choose. Your own typing is untouched.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 20)
            .padding(.vertical, 14)
            DSDivider()
            VStack(alignment: .leading, spacing: 12) {
                Text("Template").font(.ds(13, .semibold)).foregroundStyle(DS.text1)
                DSSegmentedPill(
                    options: NoteTemplate.allCases.map { .init($0, label: $0.label) },
                    selection: $template,
                    height: 28)
                    .disabled(working)
                    .accessibilityElement(children: .contain)
                    .accessibilityLabel("Template")
                if !model.online {
                    Text("Needs a connection").font(.dsMeta).foregroundStyle(DS.muted)
                }
                if let error {
                    DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                }
                if let notice {
                    DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill", text: notice)
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            DSDivider()
            HStack(spacing: 10) {
                Spacer(minLength: 8)
                if working { ProgressView().controlSize(.small) }
                Button("Cancel", action: onClose)
                    .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                    .keyboardShortcut(.cancelAction)
                Button("Regenerate") { Task { await go() } }
                    .buttonStyle(DSButtonStyle(kind: .primary, height: 28))
                    .disabled(blocked)
                    .keyboardShortcut(.defaultAction)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
        }
        .frame(width: 520)
        .background(DS.bg)
        .onAppear {
            template = model.generation?.template.flatMap { NoteTemplate(rawValue: $0) } ?? .auto
        }
    }

    private func go() async {
        working = true
        error = nil
        notice = nil
        defer { working = false }
        do {
            if let refused = try await model.regenerate(as: template) {
                notice = refused
            } else {
                onClose()
            }
        } catch {
            self.error = AuthCopy.message(for: error)
        }
    }
}
