import SwiftUI

/// The workspace's names and terms (Sprint 35).
///
/// The list is the safety mechanism. Terms get here from corrections —
/// you fix a name once and the workspace offers to remember it — and a
/// vocabulary that learns without showing you what it learned is one you
/// cannot trust. So: everything visible, everything removable by whoever
/// added it, nothing learned silently.
struct GlossaryView: View {
    @EnvironmentObject private var app: AppState
    @State private var terms: [GlossaryTerm] = []
    @State private var loading = true
    @State private var draft = ""
    @State private var kind: GlossaryKind = .person
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Spellings this workspace uses — people, companies, products. They are given to the transcriber before each recording, so it hears them right instead of guessing. Fixing a name in a note offers to add it here.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 8) {
                TextField("John Mayer", text: $draft)
                    .textFieldStyle(.plain)
                    .font(.ds(15))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 8)
                    .background(RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous)
                        .fill(DS.surface2))
                    .onSubmit { Task { await add() } }
                    .accessibilityLabel("Term")
                Button("Add") { Task { await add() } }
                    .buttonStyle(DSButtonStyle(kind: .primary, size: 14, height: 34))
                    .disabled(busy || draft.trimmingCharacters(in: .whitespaces).count < 2)
            }
            DSSegmentedPill(
                options: GlossaryKind.allCases.map { .init($0, label: $0.label) },
                selection: $kind, height: 28)
                .accessibilityElement(children: .contain)
                .accessibilityLabel("Kind of term")

            if let error {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
            }
            if loading {
                ProgressView().controlSize(.small)
            } else if terms.isEmpty {
                Text("Nothing yet. The first time you correct a name in a note, we'll offer to remember it.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                VStack(spacing: 0) {
                    ForEach(terms) { term in
                        row(term)
                        if term.id != terms.last?.id { Divider().overlay(DS.line) }
                    }
                }
            }
        }
        .task { await load() }
    }

    private func row(_ term: GlossaryTerm) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(term.term)
                    .font(.ds(15, .medium))
                    .foregroundStyle(DS.text1)
                if !term.heardAs.isEmpty {
                    Text("heard as \(term.heardAs.joined(separator: ", "))")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Text(term.kind.rawValue)
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
            Spacer(minLength: 8)
            if term.canDelete {
                Button("Forget") { Task { await forget(term) } }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 13, height: 28))
                    .disabled(busy)
                    .accessibilityLabel("Forget \(term.term)")
            }
        }
        .padding(.vertical, 8)
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            terms = try await app.api.glossary()
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func add() async {
        let value = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard value.count >= 2, !busy else { return }
        busy = true
        defer { busy = false }
        do {
            _ = try await app.api.rememberTerm(value, kind: kind)
            draft = ""
            await load()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func forget(_ term: GlossaryTerm) async {
        busy = true
        defer { busy = false }
        do {
            try await app.api.forgetTerm(id: term.id)
            terms.removeAll { $0.id == term.id }
        } catch {
            self.error = error.localizedDescription
        }
    }
}
