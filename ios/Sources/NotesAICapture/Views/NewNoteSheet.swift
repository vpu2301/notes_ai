import SwiftUI

/// "New from template…" — one tap to start a note from a template.
struct NewNoteSheet: View {
    @EnvironmentObject private var app: AppState
    let onClose: () -> Void

    @State private var templates: [TemplateSummary]?
    @State private var error: String?
    @State private var creating: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if let error {
                        DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                        Button("Try again") { Task { await load() } }
                            .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 34))
                    } else if let templates {
                        if templates.isEmpty {
                            Text("Your workspace has no note templates yet.")
                                .font(.dsBody)
                                .foregroundStyle(DS.muted)
                        } else {
                            VStack(spacing: 0) {
                                ForEach(templates) { template in
                                    row(template)
                                    if template.id != templates.last?.id { DSDivider().padding(.leading, 16) }
                                }
                            }
                            .dsCard(padding: 0)
                        }
                    } else {
                        DSSkeleton(height: 48)
                        DSSkeleton(height: 48)
                        DSSkeleton(height: 48)
                    }
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(DS.bg)
            .navigationTitle("New from template")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) { Button("Cancel", action: onClose) }
            }
            .task { await load() }
        }
    }

    private func row(_ template: TemplateSummary) -> some View {
        Button {
            Task { await create(template) }
        } label: {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(template.name)
                        .font(.ds(15, .medium))
                        .foregroundStyle(DS.text1)
                    Text([template.category, template.language.uppercased()]
                        .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                }
                Spacer(minLength: 8)
                if creating == template.id {
                    ProgressView().controlSize(.small)
                } else {
                    Image(systemName: "chevron.right")
                        .font(.dsSymbol(12, .semibold))
                        .foregroundStyle(DS.muted)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(creating != nil)
    }

    private func load() async {
        error = nil
        do {
            templates = try await app.api.fetchTemplates().filter { $0.status != "archived" }
        } catch {
            self.error = AuthCopy.message(for: error)
        }
    }

    private func create(_ template: TemplateSummary) async {
        creating = template.id
        defer { creating = nil }
        if let id = await app.createBlankNote(templateId: template.id) {
            onClose()
            app.openNote(id)
        }
    }
}
