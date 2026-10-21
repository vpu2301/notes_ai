import SwiftUI

/// Settings › Note writing — how this workspace's notes are written: the templates, the
/// instructions, automatic writing and the model behaviour. Read-only: an admin edits them on the web.
struct NoteWritingView: View {
    @EnvironmentObject private var app: AppState
    @State private var settings: AISettings?
    @State private var instructions: AIInstructions?
    /// P2 — the writer's templates in the device's language; nil when they could not be loaded.
    @State private var templates: [WorkspaceTemplate]?
    @State private var loaded = false
    @State private var instructionsFailed = false

    /// The last values fetched, for this session only: shown when a reload fails offline.
    @MainActor private static var cachedSettings: AISettings?
    @MainActor private static var cachedInstructions: AIInstructions?
    @MainActor private static var off = false

    /// The template language shown: the device's, when the writer has it; else English.
    static var templateLanguage: String {
        let code = Locale.current.language.languageCode?.identifier ?? "en"
        return ["en", "de", "uk"].contains(code) ? code : "en"
    }

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
                templatesSection
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

    private var templatesSection: some View {
        section("Templates") {
            if let templates {
                Text("The shape a note is written in. A note's template is chosen when it is created, or by the writer when it is set to Automatic.")
                    .font(.dsMeta).foregroundStyle(DS.text2)
                    .fixedSize(horizontal: false, vertical: true)
                ForEach(templates, id: \.name) { template in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(template.label).foregroundStyle(DS.text1)
                        Spacer(minLength: 8)
                        Text(template.isCustomised ? "Customised" : "Built-in")
                            .foregroundStyle(template.isCustomised ? DS.accentText : DS.muted)
                    }
                    .font(.dsMeta)
                    .accessibilityElement(children: .combine)
                }
                Button("Edit on the web") { app.openWebSettingsWriting() }
                    .buttonStyle(.plain).font(.dsMeta).foregroundStyle(DS.accent)
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

    /// The effective parameters as label/value pairs, in the web page's order (P2: what the writer reads).
    static func rows(_ p: AISettings.ModelParams) -> [(String, String)] {
        func tokens(_ n: Int?) -> String { n.map { "\($0.formatted()) tokens" } ?? "Set by the model" }
        return [
            ("Temperature", p.temperature.formatted()),
            ("Output budget", tokens(p.maxOutputTokens)),
            ("Parallel calls", p.maxConcurrency.formatted()),
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
        let language = Self.templateLanguage
        async let s = Self.attempt { try await api.aiSettings() }
        async let i = Self.attempt { try await api.aiInstructions() }
        async let t = Self.attempt { try await api.aiTemplates(language: language) }
        let (settingsResult, instructionsResult, templatesResult) = await (s, i, t)
        templates = try? templatesResult.get()

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
            // P2a: the box always holds the text the writer follows — the default rules until edited.
            Text(i.isDefault ? "Default rules" : "Edited")
                .font(.dsMeta).foregroundStyle(DS.muted)
                .accessibilityIdentifier("instructions-source")
            if i.text.isEmpty {
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
            }
            HStack(spacing: 4) {
                if !i.isDefault && i.version > 0 { Text("v\(i.version) ·").font(.dsMeta).foregroundStyle(DS.muted) }
                Button("Edit on the web") { app.openWebSettingsWriting() }
                    .buttonStyle(.plain).font(.dsMeta).foregroundStyle(DS.accent)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .dsCard()
    }
}
