import SwiftUI

/// Settings › Data & AI — who processes this workspace's meetings. Read-only
/// on purpose: the acknowledgement dialog lives on the web page.
struct DataAndAIView: View {
    @EnvironmentObject private var app: AppState
    @State private var settings: AISettings?
    @State private var loading = true
    @State private var error: String?

    private static let money: NumberFormatter = {
        let f = NumberFormatter()
        f.numberStyle = .currency
        f.currencyCode = "USD"
        return f
    }()

    private func money(_ cents: Int) -> String {
        Self.money.string(from: NSNumber(value: Double(cents) / 100)) ?? "\(cents)¢"
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Recordings and notes are processed by the companies below, and by nobody else. This list is read from the routing configuration itself, so it is what actually happens to your data — not a description of it.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)

                if loading {
                    ProgressView().controlSize(.small)
                } else if let error {
                    DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                } else if let settings {
                    content(settings)
                }

                Button("Open Data & AI in the web app") { app.openWebSettingsData() }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 15, height: 40))
            }
            .padding(.horizontal, DS.gutter)
            .padding(.vertical, 12)
        }
        .background(DS.bg)
        .navigationTitle("Data & AI")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    @ViewBuilder
    private func content(_ s: AISettings) -> some View {
        if s.processors.isEmpty {
            Text("Nothing is routed anywhere for this workspace: notes are not written automatically.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
        } else {
            VStack(spacing: 0) {
                ForEach(s.processors) { processor in
                    row(processor)
                    if processor.id != s.processors.last?.id { Divider().overlay(DS.line) }
                }
            }
            .dsCard(padding: 0)
        }

        if s.effectiveTier != s.tier {
            DSNotice(
                tone: .warn, symbol: "exclamationmark.triangle.fill",
                text: "Notes are being written on the \(s.effectiveTier) tier, not \(s.tier): "
                    + s.needsAcknowledgement.map { "\($0.name) (\($0.region.uppercased()))" }
                        .joined(separator: ", ")
                    + " has not been agreed to for this workspace.")
        }
        if !s.generationEnabled {
            DSNotice(tone: .info, symbol: "pause.circle.fill",
                     text: "Automatic note writing is off for this workspace. Recordings are still transcribed, and your own notes are untouched.")
        }

        HStack(spacing: 6) {
            Text("Quality").font(.dsMeta).foregroundStyle(DS.muted)
            Text(s.effectiveTier.capitalized).font(.ds(15, .medium)).foregroundStyle(DS.text1)
            Spacer()
            Text("\(money(s.monthToDateCents)) of \(money(s.budgetCents)) this month")
                .font(.dsMeta)
                .foregroundStyle(s.monthToDateCents >= s.budgetCents ? DS.warn : DS.muted)
        }
        .accessibilityElement(children: .combine)
    }

    private func row(_ processor: AIProcessor) -> some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(processor.name).font(.ds(15, .medium)).foregroundStyle(DS.text1)
                Text(processor.purpose).font(.dsMeta).foregroundStyle(DS.muted)
            }
            Spacer(minLength: 8)
            Text(processor.region.uppercased()).font(.dsMeta).foregroundStyle(DS.muted)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 11)
        .accessibilityElement(children: .combine)
    }

    private func load() async {
        loading = true
        do {
            settings = try await app.api.aiSettings()
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
        loading = false
    }
}
