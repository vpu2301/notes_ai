import SwiftUI

/// The workspace's names and terms. The list is the safety mechanism: everything
/// visible, removable by whoever added it, nothing learned silently. It also shows
/// the exact line the transcriber is given, and flags entries the server no longer sends (role labels).
struct GlossaryView: View {
    @EnvironmentObject private var app: AppState
    @State private var terms: [GlossaryTerm] = []
    @State private var hint: GlossaryHint?
    @State private var loading = true
    @State private var draft = ""
    @State private var kind: GlossaryKind = .person
    @State private var busy = false
    @State private var error: String?

    /// Entries the server keeps but no longer sends (role labels).
    private var notSent: Int { terms.filter { !$0.inHint }.count }

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
            if notSent > 0 {
                DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill",
                         text: notSent == 1
                            ? "1 entry is a role label, not a name — it is no longer sent to the transcriber; remove it"
                            : "\(notSent) entries are role labels, not names — they are no longer sent to the transcriber; remove them")
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
            if !loading {
                transcriberBlock
            }
        }
        .task { await load() }
    }

    /// Read-only: the next upload's `vocabulary_hint`, word for word from the server (not a rendering of the list).
    private var transcriberBlock: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("What the transcriber is told for the next recording")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
            Text(hint.map { $0.hint.isEmpty ? "Nothing — the transcriber gets no hint." : $0.hint }
                 ?? "Could not load the hint.")
                .font(.dsMono(12))
                .foregroundStyle(hint?.hint.isEmpty == false ? DS.text1 : DS.muted)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(10)
                .background(RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .fill(DS.surface2))
        }
        .accessibilityElement(children: .combine)
    }

    private func row(_ term: GlossaryTerm) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(term.term)
                    .font(.ds(15, .medium))
                    .foregroundStyle(term.inHint ? DS.text1 : DS.muted)
                    .strikethrough(!term.inHint)
                if !term.heardAs.isEmpty {
                    Text("heard as \(term.heardAs.joined(separator: ", "))")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                HStack(spacing: 6) {
                    Text(term.inHint
                         ? "added \(term.createdAt.formatted(date: .abbreviated, time: .omitted))"
                         : "not sent · added \(term.createdAt.formatted(date: .abbreviated, time: .omitted))")
                    if let noteId = term.sourceNoteId {
                        Text("·")
                        Button("from a note") { openSourceNote(noteId) }
                            .buttonStyle(.plain)
                            .foregroundStyle(DS.accentText)
                            .accessibilityLabel("Open the note \(term.term) was remembered from")
                    }
                }
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
            }
            Text(term.kind.label)
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
        .opacity(term.inHint ? 1 : 0.7)
    }

    private func openSourceNote(_ noteId: String) {
        app.openNote(noteId)
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
        await refreshHint()
    }

    /// The hint is the server's, so it is re-read after every change.
    private func refreshHint() async {
        hint = try? await app.api.glossaryHint()
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
            await refreshHint()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
