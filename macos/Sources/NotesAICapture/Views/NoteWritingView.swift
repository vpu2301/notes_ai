import SwiftUI

/// Settings › Note writing — how this workspace's notes are worded: the style, the
/// instructions, automatic writing and the model behaviour. Read-only: an admin edits them on the web.
struct NoteWritingView: View {
    @EnvironmentObject private var app: AppState
    @State private var settings: AISettings?
    @State private var instructions: AIInstructions?
    @State private var loaded = false
    @State private var instructionsFailed = false

    /// The last values fetched, for this session only: shown when a reload fails offline.
    @MainActor private static var cachedSettings: AISettings?
    @MainActor private static var cachedInstructions: AIInstructions?
    @MainActor private static var off = false

    static let styles = ["business", "formal", "informal", "academic"]
    static let styleHelp = [
        "business": "An executive record of what was said and decided — the notes as they are today.",
        "formal": "Full forms and no colloquial words; titles and surnames as given; one claim per sentence.",
        "informal": "Plain, direct wording with short sentences and short headings; no figure tables.",
        "academic": "Precise and hedged: who argues what, every qualifier kept, figures with their units.",
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Button { app.openWebSettingsWriting() } label: {
                Text("Only a workspace admin can change these. ")
                    .foregroundColor(DS.muted)
                + Text("Edit on the web.").foregroundColor(DS.accent)
            }
            .buttonStyle(.plain)
            .font(.dsMeta)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)

            if !loaded {
                ProgressView().controlSize(.small)
            } else {
                styleSection
                if instructions != nil || instructionsFailed {
                    NoteInstructionsSection(instructions: instructions)
                }
                automaticSection
                behaviourSection
            }
        }
        .task { await load() }
    }

    // MARK: - Sections

    private var styleSection: some View {
        section("Style") {
            if let s = settings {
                let chosen = s.writingStyle ?? "business"
                HStack(spacing: 6) {
                    ForEach(Self.styles, id: \.self) { style in
                        Text(style.capitalized)
                            .font(.ds(13 - 2, style == chosen ? .semibold : .regular))
                            .foregroundStyle(style == chosen ? DS.accentText : DS.muted)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 5)
                            .background(Capsule().fill(style == chosen ? DS.accentSoft : .clear))
                    }
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("Style: \(chosen.capitalized)")
                if let help = Self.styleHelp[chosen] {
                    Text(help).font(.dsMeta).foregroundStyle(DS.text2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let override = instructions?.profileStyle {
                    Text("Overridden by your instructions (they say: \(override.capitalized))")
                        .font(.dsMeta).foregroundStyle(DS.warn)
                        .fixedSize(horizontal: false, vertical: true)
                }
            } else {
                couldNotLoad
            }
        }
    }

    private var automaticSection: some View {
        section("Automatic writing") {
            if let s = settings {
                HStack(spacing: 6) {
                    Text("Write notes automatically after a recording")
                        .font(.dsMeta).foregroundStyle(DS.text2)
                    Spacer(minLength: 8)
                    Text(s.generationEnabled ? "On" : "Off").font(.ds(13, .medium)).foregroundStyle(DS.text1)
                }
                .accessibilityElement(children: .combine)
            } else {
                couldNotLoad
            }
        }
    }

    private var behaviourSection: some View {
        let version = settings?.modelParamsVersion ?? 0
        return DisclosureGroup {
            VStack(alignment: .leading, spacing: 6) {
                if let s = settings {
                    pair("Quality tier", s.effectiveTier.capitalized)
                    if let p = s.modelParamsEffective {
                        ForEach(Array(Self.rows(p).enumerated()), id: \.offset) { _, row in
                            pair(row.0, row.1)
                        }
                    }
                } else {
                    couldNotLoad
                }
            }
            .padding(.top, 8)
        } label: {
            Text("Advanced: model behaviour" + (version > 0 ? " (v\(version))" : ""))
                .font(.ds(13, .semibold)).foregroundStyle(DS.text1)
        }
        .tint(DS.muted)
        .dsCard()
    }

    /// The effective parameters as label/value pairs, in the web page's order.
    static func rows(_ p: AISettings.ModelParams) -> [(String, String)] {
        func tokens(_ n: Int?) -> String { n.map { "\($0.formatted()) tokens" } ?? "Set by the model" }
        let retries = ["off": "Off", "standard": "Standard", "thorough": "Thorough"]
        return [
            ("Temperature", p.temperature.formatted()),
            ("Context window", tokens(p.contextWindowTokens)),
            ("Output budget", tokens(p.maxOutputTokens)),
            ("Parallel calls", p.maxConcurrency.formatted()),
            ("Facts per pass", p.factsPerWindow.formatted()),
            ("Second reading", retries[p.retries] ?? p.retries.capitalized),
            ("“Ask this note” temperature", p.askTemperature.formatted()),
            ("“Ask this note” answer length", tokens(p.askMaxTokens)),
        ]
    }

    // MARK: - Pieces

    private func section(_ title: String, @ViewBuilder content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.ds(13, .semibold)).foregroundStyle(DS.text1)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .dsCard()
    }

    private func pair(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(label).foregroundStyle(DS.muted)
            Spacer(minLength: 8)
            Text(value).foregroundStyle(DS.text1).multilineTextAlignment(.trailing)
        }
        .font(.dsMeta)
        .accessibilityElement(children: .combine)
    }

    private var couldNotLoad: some View {
        Text("Couldn't load").font(.dsMeta).foregroundStyle(DS.muted)
    }

    // MARK: - Loading

    private static func attempt<T>(_ body: () async throws -> T) async -> Result<T, Error> {
        do { return .success(try await body()) } catch { return .failure(error) }
    }

    private func load() async {
        let api = app.api
        async let s = Self.attempt { try await api.aiSettings() }
        async let i = Self.attempt { try await api.aiInstructions() }
        let (settingsResult, instructionsResult) = await (s, i)

        switch settingsResult {
        case .success(let fetched):
            settings = fetched
            Self.cachedSettings = fetched
        case .failure:
            settings = Self.cachedSettings
        }

        switch instructionsResult {
        case .success(let fetched):
            instructions = fetched
            Self.cachedInstructions = fetched
            Self.off = fetched == nil
        case .failure:
            // Offline: the last card this session saw, else say it could not load.
            instructions = Self.off ? nil : Self.cachedInstructions
        }
        instructionsFailed = instructions == nil && !Self.off
        loaded = true
    }
}

/// Note writing › Instructions — how the workspace wants its notes written, read-only
/// (editing is on the web). `instructions` nil: they could not be loaded.
struct NoteInstructionsSection: View {
    @EnvironmentObject private var app: AppState
    let instructions: AIInstructions?
    @State private var showAll = false

    var body: some View {
        if let i = instructions {
            card(i)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                Text("Instructions").font(.ds(13, .semibold)).foregroundStyle(DS.text1)
                Text("Couldn't load").font(.dsMeta).foregroundStyle(DS.muted)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .dsCard()
        }
    }

    private func card(_ i: AIInstructions) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Instructions").font(.ds(13, .semibold)).foregroundStyle(DS.text1)
            if i.version == 0 {
                Text("None set. A workspace admin can add them on the web.")
                    .font(.dsMeta).foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text(i.text)
                    .font(.system(size: 13 - 2, design: .monospaced))
                    .foregroundStyle(DS.text2)
                    .lineLimit(showAll ? nil : 12)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                if !showAll && i.text.split(separator: "\n", omittingEmptySubsequences: false).count > 12 {
                    Button("Show all") { showAll = true }
                        .buttonStyle(.plain).font(.dsMeta).foregroundStyle(DS.accent)
                }
                if i.compileStatus == "failed" {
                    DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill",
                             text: AIInstructions.failedText)
                }
                if !i.understood.isEmpty {
                    heading("Understood")
                    bullets(i.understood)
                } else if i.compileStatus != "failed" {
                    Text("Nothing specific — the notes are written as usual.")
                        .font(.dsMeta).foregroundStyle(DS.muted)
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
            if let also = i.alsoSetFor {
                Text("Also set for: \(also)")
                    .font(.dsMeta).foregroundStyle(DS.text2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 4) {
                if i.version > 0 { Text("v\(i.version) ·").font(.dsMeta).foregroundStyle(DS.muted) }
                Button("Edit on the web") { app.openWebSettingsWriting() }
                    .buttonStyle(.plain).font(.dsMeta).foregroundStyle(DS.accent)
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
}
