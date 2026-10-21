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
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text("The note is written again from its recording with the template you choose. Your own typing is untouched.")
                        .font(.dsMeta).foregroundStyle(DS.muted)
                        .fixedSize(horizontal: false, vertical: true)
                    Text("Template").font(.ds(15, .semibold)).foregroundStyle(DS.text1)
                    ScrollView(.horizontal, showsIndicators: false) {
                        DSSegmentedPill(
                            options: NoteTemplate.allCases.map { .init($0, label: $0.label) },
                            selection: $template,
                            height: 30)
                            .padding(.horizontal, 1)
                    }
                    .scrollBounceBehavior(.basedOnSize, axes: .horizontal)
                    .disabled(working)
                    .accessibilityElement(children: .contain)
                    .accessibilityLabel("Template")
                    if !model.online {
                        Text("Needs a connection").font(.dsMeta).foregroundStyle(DS.muted)
                    }
                    Button("Regenerate") { Task { await go() } }
                        .buttonStyle(DSButtonStyle(kind: .primary))
                        .disabled(blocked)
                    if working { ProgressView() }
                    if let error {
                        DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                    }
                    if let notice {
                        DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill", text: notice)
                    }
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(DS.bg)
            .navigationTitle("Regenerate this note")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel", action: onClose)
                }
            }
        }
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
