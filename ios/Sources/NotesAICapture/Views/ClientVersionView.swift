import SwiftUI

/// "Client version" — what this note looks like outside the workspace, built
/// by the same server function as the shared page and the PDF.
struct ClientVersionView: View {
    @ObservedObject var model: NoteViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("This is exactly what someone outside the workspace sees — on the shared page and in the PDF. Your own notes and the transcript are never part of it.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)

            if model.clientVersionLoading, model.clientVersion == nil {
                DSSkeleton(height: 24, width: 200)
                DSSkeleton(height: 72)
                DSSkeleton(height: 72)
            } else if let notice = model.clientVersionNotice {
                DSNotice(tone: .info, symbol: "info.circle", text: notice)
            } else if let doc = model.clientVersion {
                if let check = model.clientCheck, !check.warnings.isEmpty {
                    warnings(check.warnings)
                }
                if doc.sections.isEmpty {
                    DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill",
                             text: "There is nothing a client could read yet — every section is internal, empty, or the transcript.")
                } else {
                    document(doc)
                }
            }
        }
        .task(id: model.version) { await model.loadClientVersion(force: model.clientVersion != nil) }
    }

    /// Worth checking before you share — warnings, never blockers.
    private func warnings(_ items: [ChecklistItem]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            DSLabel("Worth checking before you share")
            ForEach(items) { item in
                HStack(alignment: .top, spacing: 8) {
                    Text("\(item.count)")
                        .font(.dsMono(12, .semibold))
                        .foregroundStyle(DS.warn)
                        .frame(minWidth: 18, alignment: .trailing)
                    Text(item.detail)
                        .font(.ds(14))
                        .foregroundStyle(DS.text1)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: DS.radius, style: .continuous).fill(DS.warnSoft))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Worth checking before you share")
    }

    private func document(_ doc: ClientVersion) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(doc.title.isEmpty ? "Untitled note" : doc.title)
                .font(.dsDisplay(22, .semibold))
                .foregroundStyle(DS.text1)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(doc.sections) { section in
                VStack(alignment: .leading, spacing: 6) {
                    if !section.name.isEmpty {
                        Text(section.name)
                            .font(.dsDisplay(16, .semibold))
                            .foregroundStyle(DS.text1)
                    }
                    RichTextView(text: section.text, size: 15)
                }
            }
            if doc.hiddenLines > 0 || !doc.hiddenSections.isEmpty {
                Text(hiddenLine(doc))
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .dsCard(padding: 18)
    }

    private func hiddenLine(_ doc: ClientVersion) -> String {
        var parts: [String] = []
        if !doc.hiddenSections.isEmpty {
            parts.append("\(doc.hiddenSections.count) internal \(doc.hiddenSections.count == 1 ? "section" : "sections")")
        }
        if doc.hiddenLines > 0 {
            parts.append("\(doc.hiddenLines) \(doc.hiddenLines == 1 ? "line" : "lines")")
        }
        return "Kept from the client: " + parts.joined(separator: " and ") + "."
    }
}
