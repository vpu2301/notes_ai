import SwiftUI

/// The note's versions, newest first; tapping one shows it read-only. Amendments are history only (ADR-0051).
struct HistorySheet: View {
    @ObservedObject var model: NoteViewModel
    let onClose: () -> Void

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if model.versionsLoading, model.versions.isEmpty {
                        DSSkeleton(height: 44)
                        DSSkeleton(height: 44)
                        DSSkeleton(height: 44)
                    } else if let error = model.versionsError {
                        DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                    } else if model.versions.isEmpty {
                        Text("No history yet.")
                            .font(.dsBody)
                            .foregroundStyle(DS.muted)
                    } else {
                        VStack(spacing: 0) {
                            ForEach(model.versions) { version in
                                row(version)
                                if version.id != model.versions.last?.id { DSDivider().padding(.leading, 16) }
                            }
                        }
                        .dsCard(padding: 0)
                        Text("Every save is a version. Opening one shows the note as it was; nothing is changed until you edit the current version.")
                            .font(.dsMeta)
                            .foregroundStyle(DS.muted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(DS.bg)
            .navigationTitle("History")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) { Button("Done", action: onClose) }
            }
            .task { await model.loadVersions() }
        }
    }

    private func row(_ version: NoteVersionSummary) -> some View {
        let isCurrent = version.versionNumber == model.version
        let isShown = model.viewing?.versionNumber == version.versionNumber
        return Button {
            Task {
                await model.view(version: version.versionNumber)
                onClose()
            }
        } label: {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 8) {
                        Text("Version \(version.versionNumber)")
                            .font(.ds(15, .semibold))
                            .foregroundStyle(DS.text1)
                        if isCurrent {
                            DSChip(text: "Current", tint: DS.accentText, soft: DS.accentSoft)
                        } else if isShown {
                            DSChip(text: "Showing", tint: DS.info, soft: DS.infoSoft)
                        }
                        if version.isAmendment, let type = version.amendmentType {
                            DSChip(text: type.capitalized, tint: DS.indigo, soft: DS.indigoSoft)
                        }
                    }
                    Text(formatDateTime(version.createdAt))
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                    if let reason = version.amendmentReason, !reason.isEmpty {
                        Text(reason)
                            .font(.dsMeta)
                            .foregroundStyle(DS.text3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 8)
                if model.viewingLoading, isShown {
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
        .accessibilityHint(isCurrent ? "Back to the note as it stands" : "Show this version read-only")
    }
}
