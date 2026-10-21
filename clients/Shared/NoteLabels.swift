import Foundation

/// Labels a note carries in its own language (the generation's `language`), never the
/// device locale: an English label inside a German note is a defect (B1 T6).
enum NoteLabels {
    static func alsoSaid(language: String?) -> String {
        switch language {
        case "de": return "Außerdem gesagt"
        case "uk": return "Також сказано"
        default: return "Also said"
        }
    }

    /// A3 — the transcript's "heard as" marker and the toggle that shows the words as heard.
    static func heardAs(language: String?) -> String {
        switch language {
        case "de": return "gehört als"
        case "uk": return "почуто як"
        default: return "heard as"
        }
    }

    static func asTranscribed(language: String?) -> String {
        switch language {
        case "de": return "Wie transkribiert anzeigen"
        case "uk": return "Показати як транскрибовано"
        default: return "Show as transcribed"
        }
    }

    /// B4 — what a written line is: the speaker's words, one fact, or several (`count`).
    static func provenance(language: String?, provenance: String?, count: Int) -> String? {
        let n = max(2, count)
        switch (provenance, language) {
        case ("verbatim", "de"): return "Wörtlich"
        case ("verbatim", "uk"): return "Дослівно"
        case ("verbatim", _): return "Verbatim"
        case ("paraphrase", "de"): return "Paraphrase"
        case ("paraphrase", "uk"): return "Парафраз"
        case ("paraphrase", _): return "Paraphrase"
        case ("composed", "de"): return "Aus \(n) Aussagen"
        case ("composed", "uk"): return "З \(n) висловлювань"
        case ("composed", _): return "From \(n) statements"
        default: return nil
        }
    }
}
