import AppKit
import Foundation
import Network

/// One open note: the envelope, its template's sections, the editable
/// content with debounced autosave, the
/// transcript it came from, and PDF export. Mirrors the web editor page.
@MainActor
final class NoteViewModel: ObservableObject {
    enum SaveState: Equatable {
        case saved, dirty, saving, error

        var label: String {
            switch self {
            case .saved: return "Saved"
            case .dirty: return "Unsaved"
            case .saving: return "Saving…"
            case .error: return "Save failed"
            }
        }
    }

    enum Tab: Hashable { case notes, transcript }

    let noteId: String
    /// Given by the caller (a recording made here) or learnt from the
    /// note itself, so a note made elsewhere still opens its transcript.
    @Published private(set) var jobId: String?

    @Published private(set) var note: NoteEnvelope?
    @Published private(set) var sections: [TemplateSectionDef] = []
    /// The template's display name, for the note's meta line; nil when the
    /// template could not be read (deprecated, or not ours to see).
    @Published private(set) var templateName: String?
    @Published var content: NoteContent?
    @Published private(set) var version = 0
    @Published private(set) var saveState: SaveState = .saved
    @Published private(set) var conflict = false
    /// Set when this is not our note and nobody shared it with us — a
    /// workspace admin opening a colleague's note. Every read is then sent
    /// with this purpose (the server records it) and the screen says so.
    @Published private(set) var readPurpose: ReadPurpose?
    @Published private(set) var loadError: String?
    @Published private(set) var isLoading = true
    @Published private(set) var busy = false
    @Published var actionError: String?
    @Published var tab: Tab = .notes

    /// Sections whose text is the raw transcript (dialogue-shaped): shown
    /// behind the Transcript tab, never among the notes.
    var transcriptSections: [TemplateSectionDef] {
        sections.filter { TranscriptText.isTranscript(content?.section($0.id).text ?? "") }
    }
    var noteSections: [TemplateSectionDef] {
        let hidden = Set(transcriptSections.map(\.id))
        return sections.filter { !hidden.contains($0.id) }
    }
    /// The transcript as text turns, for a note without a readable job.
    var textTurns: [TranscriptText.Turn] {
        transcriptSections.flatMap { TranscriptText.turns(content?.section($0.id).text ?? "") }
    }
    var hasTranscript: Bool { jobId != nil || !transcriptSections.isEmpty }

    /// Who can see the note (0016); loaded lazily the first time the menu asks.
    @Published private(set) var sharing: SharingView?
    /// Set after a successful delete so the view can close itself.
    @Published private(set) var deleted = false
    @Published private(set) var turns: [TranscriptTurn]?
    /// Label → display name for the transcript's speakers (people's names
    /// where given, "Speaker N" elsewhere). Kept apart from `turns` so a
    /// rename repaints every turn of that speaker at once.
    @Published private(set) var speakerNames: [String: String] = [:]
    @Published private(set) var transcriptError: String?
    @Published private(set) var renamingSpeaker = false
    /// Roster (after merges) and talk time per speaker.
    @Published private(set) var speakers: [String] = []
    @Published private(set) var speakerStats: [SpeakerStat] = []
    /// The latest speaker edit, while it can be undone ("Merged into Anna ·
    /// Undo", "Moved 3 turns to Tom · Undo").
    @Published private(set) var lastEdit: LastSpeakerEdit?
    /// Sprint 30: the result revision the turns were read from; every move
    /// sends it back. Nil from servers that cannot move turns.
    @Published private(set) var resultRev: Int?
    /// Names offered when renaming (the calendar event's invitees).
    @Published private(set) var nameCandidates: [String] = []
    /// Sprint 31: label → "local"/"remote" (empty for mono jobs).
    @Published private(set) var speakerSides: [String: String] = [:]
    /// Sprint 31: label → how its name was given ("channel", "typed", …).
    @Published private(set) var speakerNameSources: [String: String] = [:]
    /// Sprint 32: names the server heard people give themselves, not yet
    /// accepted or dismissed. Empty while the server's switch is off.
    @Published private(set) var nameSuggestions: [NameSuggestion] = []
    /// Sprint 32: an older engine labelled this transcript and its audio
    /// is still there — the re-label banner offers a fresh run.
    @Published private(set) var relabelAvailable = false
    /// The re-label banner was closed in this view.
    @Published private(set) var relabelBannerDismissed = false
    /// Sprint 32: the turn a suggestion's quote points at — scrolled to and
    /// highlighted for `highlightDuration`.
    @Published private(set) var revealedTurn: TurnReveal?
    /// Sprint 32: what assistive technology should say after a speaker
    /// edit ("Merged", "Moved 3 turns", "Re-labelling finished"). The view
    /// posts it; the model only decides the words.
    @Published private(set) var announcement: Announcement?
    /// Turns picked for a multi-turn move (ids = `TranscriptTurn.id`).
    @Published var selectedTurnIds: Set<Int> = []
    /// iOS "Select" mode: taps pick turns instead of opening menus.
    @Published var selecting = false
    /// "Speakers were updated elsewhere." after a refused stale move.
    @Published var speakerNotice: String?
    /// Small speakers the person said to keep (not merge) in this view.
    @Published var keptSpeakers: Set<String> = []
    /// Note text before/after the last merge rewrote it, for an exact undo.
    private var mergeRewrite: (before: NoteContent, after: NoteContent)?
    /// Speaker edits need the network; offline the controls are disabled.
    @Published private(set) var online = true
    /// Sprint 29 — "Wrong number of speakers?": the re-label in this view.
    @Published private(set) var relabel: RelabelState = .idle
    /// The server can put back the labelling the last re-run replaced.
    @Published private(set) var canUndoRelabel = false
    /// "high" | "low" | nil — how sure the diarizer is of the speaker count.
    @Published private(set) var countConfidence: String?
    /// The exact count a person asked for on the current labelling.
    @Published private(set) var speakersHint: Int?
    /// Live merges on the current labelling; a re-label replaces them.
    @Published private(set) var mergeCount = 0
    /// "Looks right" on the low-confidence banner, remembered per job.
    @Published private(set) var countBannerDismissed = false
    /// How often a running re-label is polled.
    var relabelPollInterval: Duration = .seconds(3)
    /// Told when a re-label starts following and when it stops (job id,
    /// running) — the Mac's recents list says "Re-labelling speakers…".
    var onRelabellingChange: (@MainActor (String, Bool) -> Void)?
    /// The count the last re-label asked for, for "Try again".
    private var lastRelabelRequest: Int?
    private var relabelTask: Task<Void, Never>?
    private let pathMonitor = NWPathMonitor()


    /// "Ask this note": the thread under the document. Lives here only —
    /// the server answers one question at a time and keeps nothing.
    @Published private(set) var chat: [ChatMessage] = []
    @Published private(set) var asking = false
    @Published var askError: String?

    struct ChatMessage: Identifiable, Equatable {
        let id = UUID()
        let role: AskTurn.Role
        let text: String
    }

    private let api: APIClient
    /// The autosave timer (cancelled and restarted on every edit).
    private var saveTask: Task<Void, Never>?
    /// The write on the wire, if one is running.
    private var saveInFlight: Task<Void, Never>?
    private var pending: (content: NoteContent, version: Int)?
    private static let autosaveDelay: Duration = .milliseconds(900)

    init(noteId: String, jobId: String?, api: APIClient) {
        self.noteId = noteId
        self.jobId = jobId
        self.api = api
        pathMonitor.pathUpdateHandler = { [weak self] path in
            let satisfied = path.status == .satisfied
            Task { @MainActor in self?.online = satisfied }
        }
        pathMonitor.start(queue: .global(qos: .utility))
    }

    deinit { pathMonitor.cancel() }

    /// A note is a living document (ADR-0051): editable until cancelled.
    var isDraft: Bool {
        guard let status = note?.status else { return false }
        return status != .cancelled
    }

    /// "Ada's note" — who this note belongs to, when it is not ours.
    var oversightLabel: String? {
        guard readPurpose != nil else { return nil }
        let name = note?.primaryAuthorName?.trimmingCharacters(in: .whitespaces) ?? ""
        return name.isEmpty ? "A colleague's note" : "\(name)'s note"
    }
    var editable: Bool { isDraft }

    // MARK: - Load

    func load() async {
        loadError = nil
        isLoading = note == nil
        do {
            let envelope: NoteEnvelope
            do {
                envelope = try await api.fetchNote(id: noteId)
                readPurpose = nil
            } catch let error as APIError where error.needsReadPurpose {
                // Not our note: read it as a reviewer, on the record.
                envelope = try await api.fetchNote(id: noteId, purpose: .review)
                readPurpose = .review
            }
            note = envelope
            content = envelope.content
            if jobId == nil, let job = envelope.sourceJobId { jobId = job }
            version = envelope.currentVersionNumber
            saveState = .saved
            conflict = false
            if let templateId = envelope.content?.templateId,
               let template = try? await api.fetchTemplate(id: templateId) {
                templateName = template.name
                sections = template.schemaJsonb.sections.sorted { ($0.order ?? 0) < ($1.order ?? 0) }
            } else {
                // Template unavailable: the envelope's labels as plain text sections.
                templateName = nil
                sections = (envelope.sectionLabels ?? []).map {
                    TemplateSectionDef(id: $0.sectionKey,
                                       name: $0.name["en"] ?? $0.name["uk"] ?? $0.sectionKey,
                                       fieldType: "free_text", required: nil, minChars: nil, order: nil)
                }
            }
        } catch {
            loadError = error.localizedDescription
        }
        isLoading = false
    }

    func loadTranscript() async {
        guard turns == nil, transcriptError == nil, let jobId else { return }
        do {
            apply(try await api.transcript(jobId: jobId))
        } catch {
            transcriptError = error.localizedDescription
            return
        }
        countBannerDismissed = UserDefaults.standard.bool(forKey: Self.countBannerKey(jobId))
        // A re-label started earlier (here, on the web, on another device)
        // may still be running: follow it rather than offer a second one.
        if let job = try? await api.jobStatus(id: jobId) {
            canUndoRelabel = job.canUndoRediarize ?? false
            if job.isRelabelling { followRelabel(jobId: jobId) }
        }
    }

    private func apply(_ result: TranscriptResult) {
        speakerNames = result.speakerNames ?? [:]
        speakers = result.speakers ?? []
        speakerStats = result.speakerStats ?? []
        turns = result.turns ?? []
        countConfidence = result.countConfidence
        speakersHint = result.speakersHint
        mergeCount = result.edits?.count ?? 0
        resultRev = result.resultRev
        nameCandidates = result.nameCandidates ?? []
        speakerSides = result.speakerSides ?? [:]
        speakerNameSources = result.speakerNameSources ?? [:]
        nameSuggestions = result.nameSuggestions ?? []
        relabelAvailable = result.relabelAvailable ?? false
        // A selection is of the turns as they were; drop picks that are gone.
        let ids = Set((result.turns ?? []).map(\.id))
        selectedTurnIds.formIntersection(ids)
    }


    // MARK: - Speakers

    /// Whether the recording was diarized (anyone was told apart).
    var diarized: Bool { (turns ?? []).contains { $0.speaker != nil } }

    var speakerCount: Int { Set((turns ?? []).compactMap(\.speaker)).count }

    func displayName(for turn: TranscriptTurn) -> String {
        guard let label = turn.speaker else { return unknownSpeakerName }
        return speakerNames[label] ?? turn.name ?? defaultSpeakerName(label)
    }

    /// Rename a speaker everywhere: on the job (so the web app agrees), in
    /// this transcript, and — while the note is live — in the note body,
    /// whose turn lines start with the name. A cancelled note is a record;
    /// its text stays and only the transcript shows the new name.
    ///
    /// Sprint 30: `picked` says the name was chosen from the candidate
    /// list (sent as `sources`, a metric only); nil works it out from the
    /// candidates. Sprint 32: `source` overrides both (an accepted
    /// suggestion). Returns whether a new name was saved.
    @discardableResult
    func renameSpeaker(label: String, to rawName: String, picked: Bool? = nil,
                       source: SpeakerNameSource? = nil) async -> Bool {
        // Without a readable job the "label" is the name as it stands in
        // the note text; the rename rewrites the turn prefixes and the note
        // autosaves, so it is on the server either way.
        let textOnly = jobId == nil || transcriptError != nil
        let from = textOnly ? label : (speakerNames[label] ?? defaultSpeakerName(label))
        let trimmed = rawName.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        let to = trimmed.isEmpty ? (textOnly ? from : defaultSpeakerName(label)) : String(trimmed.prefix(80))
        guard to != from else { return false }
        guard let jobId, !textOnly else {
            renameSpeakerInNote(from: from, to: to)
            return true
        }

        // Only the names people gave are stored; defaults are implied.
        var custom = givenNames
        if to == defaultSpeakerName(label) { custom.removeValue(forKey: label) } else { custom[label] = to }

        renamingSpeaker = true
        defer { renamingSpeaker = false }
        do {
            var sources: [String: SpeakerNameSource]?
            if custom[label] != nil {
                sources = [label: source ?? ((picked ?? nameCandidates.contains(to)) ? .picklist : .typed)]
            }
            let stored = try await api.setSpeakerNames(jobId: jobId, names: custom, sources: sources)
            speakerNames = namesAfterSaving(stored)
            speakerNameSources = SpeakerChannelMarkers.sources(speakerNameSources, afterRenaming: label,
                                                               sent: sources?[label])
            // A name given by hand settles what a suggestion was offering.
            if custom[label] != nil { nameSuggestions.removeAll { $0.label == label } }
            renameSpeakerInNote(from: from, to: speakerNames[label] ?? to)
            return true
        } catch {
            actionError = error.localizedDescription
            return false
        }
    }

    /// The names people gave; defaults ("Speaker 2") are implied, never stored.
    private var givenNames: [String: String] {
        speakerNames.filter { $0.value != defaultSpeakerName($0.key) }
    }

    /// Every roster label's display name after a PUT answered with `stored`.
    private func namesAfterSaving(_ stored: [String: String]) -> [String: String] {
        var merged: [String: String] = [:]
        for l in speakerNames.keys { merged[l] = stored[l] ?? defaultSpeakerName(l) }
        return merged
    }

    func name(for label: String) -> String { speakerNames[label] ?? defaultSpeakerName(label) }

    // MARK: - Call sides (Sprint 31)

    /// The side glyph for a roster chip; nil for mono jobs.
    func side(for label: String) -> SpeakerSide? {
        SpeakerChannelMarkers.side(of: label, in: speakerSides)
    }

    /// The name was given from the channel split — shown with
    /// "· from your microphone" and an ✕.
    func isChannelNamed(_ label: String) -> Bool {
        SpeakerChannelMarkers.isChannelNamed(label, sources: speakerNameSources)
    }

    /// The ✕: remove the channel name. The PUT leaves the label out of
    /// `names` (every other name kept); the server records "cleared" and
    /// never applies the channel name again.
    func clearChannelName(_ label: String) async {
        await renameSpeaker(label: label, to: "")
    }

    /// The one small speaker worth asking about (largest first), if any.
    var smallSpeakerPrompt: (speaker: SpeakerStat, targets: [String])? {
        // The count question comes first: merging a small speaker is moot
        // until the number of people is settled. Never both banners.
        guard speakers.count > 1, !showsCountBanner, !showsRelabelBanner, relabel != .running else { return nil }
        let largest = speakerStats.sorted { $0.speechMs > $1.speechMs }
        guard let small = largest.first(where: {
            $0.isSmall && !keptSpeakers.contains($0.label) && speakers.contains($0.label)
        }) else { return nil }
        return (small, largest.filter { $0.label != small.label }.prefix(2).map(\.label))
    }

    /// Merge `from` into `into` on the job; the transcript reloads and the
    /// note's turn lines follow, as on a rename. Needs the network: an edit
    /// replayed later against a changed roster would be wrong, so nothing queues.
    func mergeSpeaker(from: String, into: String) async {
        guard let jobId, online, !renamingSpeaker else { return }
        let fromName = name(for: from)
        renamingSpeaker = true
        defer { renamingSpeaker = false }
        do {
            let res = try await api.mergeSpeakers(jobId: jobId, from: from, into: into)
            speakers = res.speakers
            speakerStats = res.speakerStats
            speakerNames = res.speakerNames
            mergeRewrite = nil
            if editable, let before = content {
                renameSpeakerInNote(from: fromName, to: res.speakerNames[into] ?? defaultSpeakerName(into))
                if let after = content, after != before { mergeRewrite = (before, after) }
            }
            apply(try await api.transcript(jobId: jobId))
            offerUndo(LastSpeakerEdit(editId: res.editId,
                                      summary: "Merged into \(res.speakerNames[into] ?? name(for: into))"))
            announce("Merged")
        } catch {
            actionError = error.localizedDescription
        }
    }

    /// Keep "… · Undo" up for ten seconds (Sprint 28's window).
    private func offerUndo(_ edit: LastSpeakerEdit) {
        lastEdit = edit
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(10))
            if self?.lastEdit?.editId == edit.editId { self?.lastEdit = nil }
        }
    }

    func undoLastSpeakerEdit() async {
        guard let jobId, online, let edit = lastEdit, !renamingSpeaker else { return }
        if let restore = edit.restore {
            await undoAccept(restore, jobId: jobId)
            return
        }
        renamingSpeaker = true
        defer { renamingSpeaker = false }
        do {
            try await api.undoSpeakerEdit(jobId: jobId, editId: edit.editId)
            lastEdit = nil
            if let rewrite = mergeRewrite {
                if content == rewrite.after { commit(rewrite.before) } else {
                    actionError = "Note text was edited; speaker names in the note were not reverted."
                }
            }
            mergeRewrite = nil
            apply(try await api.transcript(jobId: jobId))
            announce("Undone")
        } catch {
            actionError = error.localizedDescription
        }
    }

    // MARK: - Turn-level correction (Sprint 30)

    /// The latest speaker edit and what it did, for "… · Undo".
    struct LastSpeakerEdit: Equatable {
        let editId: String
        let summary: String
        /// Sprint 32: an accepted suggestion is undone by putting these
        /// names back, not by the server's edit log.
        var restore: NameRestore? = nil
    }

    /// The names before a suggestion was accepted.
    struct NameRestore: Equatable {
        let label: String
        let names: [String: String]
        let sources: [String: String]
        let suggestion: NameSuggestion
    }

    /// The server takes at most this many segment indices per move.
    nonisolated static let maxSegmentsPerMove = 500
    /// …and at most this many live speakers.
    nonisolated static let maxSpeakers = 8

    /// Whether speakers can be changed right now: a readable job, online
    /// (an edit replayed later against a changed roster would be wrong),
    /// nothing else in flight, and no re-label running.
    var canEditSpeakers: Bool {
        jobId != nil && transcriptError == nil && online && !renamingSpeaker && relabel != .running
    }

    /// Whether this turn can be moved (the server sent its segments).
    func canMove(_ turn: TranscriptTurn) -> Bool { resultRev != nil && turn.isMovable }

    /// Whether any turn can be moved — "Select" is offered only then.
    var canMoveTurns: Bool { resultRev != nil && (turns ?? []).contains(where: \.isMovable) }

    /// "New speaker" is offered while there is room for one more.
    var canAddSpeaker: Bool { speakers.count < Self.maxSpeakers }

    /// Where the given turns can go: every roster speaker except the one
    /// they all already belong to.
    func moveTargets(for turns: [TranscriptTurn]) -> [String] {
        let current = Set(turns.map(\.speaker))
        return speakers.filter { !(current.count == 1 && current.contains($0)) }
    }

    /// Whether "Unknown" makes sense: some turn is attributed to someone.
    func canMoveToUnknown(_ turns: [TranscriptTurn]) -> Bool { turns.contains { $0.speaker != nil } }

    /// The picked turns, in transcript order.
    var selectedTurns: [TranscriptTurn] { (turns ?? []).filter { selectedTurnIds.contains($0.id) } }

    /// "Move 3 turns to"
    var moveSelectionTitle: String {
        let n = selectedTurnIds.count
        return "Move \(n) \(n == 1 ? "turn" : "turns") to"
    }

    func toggleSelection(_ turn: TranscriptTurn) {
        guard canMove(turn) else { return }
        if selectedTurnIds.contains(turn.id) { selectedTurnIds.remove(turn.id) } else { selectedTurnIds.insert(turn.id) }
    }

    func endSelection() {
        selecting = false
        selectedTurnIds = []
    }

    /// One move's indices: the turns' own `segment_indices`, concatenated
    /// as they came (opaque — artifact space, never an index into
    /// `segments`), each index once.
    nonisolated static func segmentIndices(of turns: [TranscriptTurn]) -> [Int] {
        var seen = Set<Int>()
        return turns.flatMap { $0.segmentIndices ?? [] }.filter { seen.insert($0).inserted }
    }

    /// The display name a move went to, for "Moved … to Tom".
    private func targetName(_ target: ReassignTarget, created: String?, names: [String: String]) -> String {
        switch target {
        case .speaker(let label): return names[label] ?? name(for: label)
        case .new: return created.map { names[$0] ?? defaultSpeakerName($0) } ?? "a new speaker"
        case .unknown: return unknownSpeakerName
        }
    }

    /// Move turns to another speaker, a new one, or Unknown — one call for
    /// however many turns. A result changed elsewhere since it was read is
    /// reloaded and the person told so; nothing is retried behind their back.
    func moveTurns(_ moving: [TranscriptTurn], to target: ReassignTarget) async {
        guard let jobId, let rev = resultRev, canEditSpeakers else { return }
        let indices = Self.segmentIndices(of: moving.filter(canMove))
        guard !indices.isEmpty else { return }
        guard indices.count <= Self.maxSegmentsPerMove else {
            actionError = SpeakerEditError.tooManySegments.localizedDescription
            return
        }
        let count = moving.count
        speakerNotice = nil
        renamingSpeaker = true
        defer { renamingSpeaker = false }
        do {
            let res = try await api.reassignTurns(jobId: jobId, resultRev: rev,
                                                  segmentIndices: indices, to: target)
            speakers = res.speakers
            speakerStats = res.speakerStats
            speakerNames = res.speakerNames
            mergeRewrite = nil
            let to = targetName(target, created: res.createdLabel, names: res.speakerNames)
            endSelection()
            apply(try await api.transcript(jobId: jobId))
            offerUndo(LastSpeakerEdit(editId: res.editId,
                                      summary: "Moved \(count) \(count == 1 ? "turn" : "turns") to \(to)"))
            announce(count == 1 ? "Moved 1 turn" : "Moved \(count) turns")
        } catch SpeakerEditError.staleResultRev {
            await reloadAfterConflict()
        } catch {
            actionError = error.localizedDescription
        }
    }

    /// The move was refused because the speakers changed elsewhere: show
    /// the result as it is now, drop the picks made on the old one.
    private func reloadAfterConflict() async {
        guard let jobId else { return }
        endSelection()
        lastEdit = nil
        if let fresh = try? await api.transcript(jobId: jobId) { apply(fresh) }
        speakerNotice = "Speakers were updated elsewhere."
    }

    /// "Reset speaker edits": the confirm step's copy.
    nonisolated static let resetConfirmTitle = "Reset speaker edits?"
    nonisolated static let resetConfirmMessage =
        "All merges and moved turns in this transcript will be undone."

    /// Whether there is anything to reset.
    var canResetSpeakerEdits: Bool { mergeCount > 0 }

    /// Undo every live merge and move of this result (behind a confirm).
    func resetSpeakerEdits() async {
        guard let jobId, canEditSpeakers else { return }
        renamingSpeaker = true
        defer { renamingSpeaker = false }
        do {
            try await api.resetSpeakerEdits(jobId: jobId)
            lastEdit = nil
            mergeRewrite = nil
            keptSpeakers = []
            speakerNotice = nil
            endSelection()
            apply(try await api.transcript(jobId: jobId))
            announce("Speaker edits reset")
        } catch {
            actionError = error.localizedDescription
        }
    }

    /// Candidate names for renaming `label`: the offered ones not already
    /// used on another speaker.
    func nameSuggestions(for label: String) -> [String] {
        Self.picklist(candidates: nameCandidates, names: speakerNames, renaming: label)
    }

    nonisolated static func picklist(candidates: [String], names: [String: String],
                                     renaming label: String) -> [String] {
        let used = Set(names.filter { $0.key != label }.map { $0.value.lowercased() })
        return candidates.filter { !used.contains($0.lowercased()) }
    }

    /// The picklist as a completion list for what is typed so far: all of
    /// it while the field still holds the current name (or nothing), else
    /// the names containing the text.
    func nameCompletions(for label: String, typed: String) -> [String] {
        Self.completions(nameSuggestions(for: label), typed: typed, current: name(for: label))
    }

    nonisolated static func completions(_ suggestions: [String], typed: String, current: String) -> [String] {
        let query = typed.trimmingCharacters(in: .whitespaces)
        guard !query.isEmpty, query != current else { return suggestions }
        return suggestions.filter { $0.localizedCaseInsensitiveContains(query) && $0 != query }
    }

    // MARK: - Speaker count (Sprint 29)

    enum RelabelState: Equatable {
        case idle
        /// Queued or running on the server; the transcript stays readable.
        case running
        /// Finished: "Now N speakers · Undo".
        case done(speakers: Int)
        /// "Couldn't re-label speakers — Try again"; the old labels stay.
        case failed
    }

    /// "We're not sure how many people spoke." — the diarizer said so, the
    /// person has not already answered (a count, or "Looks right"), and no
    /// re-label is on its way.
    var showsCountBanner: Bool {
        !showsRelabelBanner
            && Self.showsCountBanner(confidence: countConfidence, hint: speakersHint,
                                     dismissed: countBannerDismissed, relabelling: relabel == .running)
    }

    nonisolated static func showsCountBanner(confidence: String?, hint: Int?, dismissed: Bool,
                                 relabelling: Bool) -> Bool {
        confidence == "low" && hint == nil && !dismissed && !relabelling
    }

    /// "Only 2 voices could be told apart." — the person asked for more
    /// speakers than the recording holds; none are made up to match.
    var hintShortfall: String? {
        guard let hint = speakersHint, !speakers.isEmpty, speakers.count < hint else { return nil }
        return "Only \(speakers.count) \(speakers.count == 1 ? "voice" : "voices") could be told apart."
    }

    /// The confirm step's warning when merges would be lost.
    var relabelReplacesMerges: String? {
        guard mergeCount > 0 else { return nil }
        return mergeCount == 1
            ? "Your 1 merge will be replaced by the new result."
            : "Your \(mergeCount) merges will be replaced by the new result."
    }

    /// Where the picker starts: the count asked for last, else the roster's.
    var suggestedSpeakerCount: Int { min(max(speakersHint ?? speakers.count, 1), 8) }

    /// "Looks right": hide the banner for this job, on this device, for good.
    func dismissCountBanner() {
        guard let jobId else { return }
        countBannerDismissed = true
        UserDefaults.standard.set(true, forKey: Self.countBannerKey(jobId))
    }

    nonisolated static func countBannerKey(_ jobId: String) -> String { "speakerCountConfirmed.\(jobId)" }

    /// Re-run speaker separation for `expected` people (nil: let the
    /// diarizer count). Needs the network — nothing queues offline, for the
    /// same reason a merge does not.
    func relabelSpeakers(expected: Int?) async {
        guard let jobId, online, relabel != .running, !renamingSpeaker else { return }
        lastRelabelRequest = expected
        renamingSpeaker = true
        do {
            _ = try await api.rediarize(jobId: jobId, speakersExpected: expected)
        } catch RediarizeError.inProgress {
            // One is already running (another device, the web app): follow it.
        } catch {
            renamingSpeaker = false
            actionError = error.localizedDescription
            return
        }
        renamingSpeaker = false
        // The merges belong to the labelling being replaced.
        lastEdit = nil
        endSelection()
        mergeRewrite = nil
        keptSpeakers = []
        followRelabel(jobId: jobId)
    }

    /// "Try again" after a failed re-label: the same count as before.
    func retryRelabel() async {
        relabel = .idle
        await relabelSpeakers(expected: lastRelabelRequest)
    }

    /// Put back the labelling the re-run replaced (one step only).
    func undoRelabel() async {
        guard let jobId, online, case .done = relabel, !renamingSpeaker else { return }
        renamingSpeaker = true
        defer { renamingSpeaker = false }
        do {
            _ = try await api.undoRediarize(jobId: jobId)
            relabel = .idle
            canUndoRelabel = false
            lastEdit = nil
            apply(try await api.transcript(jobId: jobId))
        } catch RediarizeError.nothingToUndo {
            relabel = .idle
            canUndoRelabel = false
        } catch {
            actionError = error.localizedDescription
        }
    }

    /// Clear "Now N speakers" or the failure line.
    func dismissRelabelResult() {
        if relabel != .running { relabel = .idle }
    }

    /// Poll the job every `relabelPollInterval` until the re-label settles.
    ///
    /// The task holds the client, not this model: a note closed mid-run
    /// stops being updated, but whoever listens on `onRelabellingChange`
    /// still hears when the run ends.
    private func followRelabel(jobId: String) {
        relabelTask?.cancel()
        relabel = .running
        let api = api
        let interval = relabelPollInterval
        let report = onRelabellingChange
        report?(jobId, true)
        relabelTask = Task { [weak self] in
            var settled: TranscriptionJob?
            while !Task.isCancelled {
                try? await Task.sleep(for: interval)
                if self == nil && report == nil { return }
                // A failed poll is a blip, not a verdict: keep asking.
                guard let job = try? await api.jobStatus(id: jobId) else { continue }
                if !job.isRelabelling {
                    settled = job
                    break
                }
            }
            // Cancelled: a newer follow took over and reports for itself.
            if Task.isCancelled { return }
            report?(jobId, false)
            guard let settled, let self else { return }
            await self.finishRelabel(settled, jobId: jobId)
        }
    }

    private func finishRelabel(_ job: TranscriptionJob, jobId: String) async {
        canUndoRelabel = job.canUndoRediarize ?? false
        guard job.diarizationStatus != "failed" else {
            relabel = .failed
            announce("Couldn't re-label speakers")
            return
        }
        do {
            apply(try await api.transcript(jobId: jobId))
            relabel = .done(speakers: speakers.count)
            announce("Re-labelling finished")
        } catch {
            relabel = .failed
            announce("Couldn't re-label speakers")
        }
    }

    // MARK: - Name suggestions and the re-label banner (Sprint 32)

    /// Something for assistive technology to say once. The token makes
    /// the same words said twice two announcements.
    struct Announcement: Equatable {
        let text: String
        var token = UUID()
    }

    /// A request to scroll to a turn and highlight it.
    struct TurnReveal: Equatable {
        let turnId: Int
        var token = UUID()
    }

    /// How long a revealed turn stays highlighted.
    var highlightDuration: Duration = .seconds(2)

    private func announce(_ text: String) {
        announcement = Announcement(text: text)
    }

    /// The suggestion shown under `label`'s chip, if any.
    func suggestion(for label: String) -> NameSuggestion? {
        Self.visibleSuggestions(nameSuggestions, speakers: speakers, names: speakerNames)
            .first { $0.label == label }
    }

    /// The suggestions worth showing: one per speaker still on the roster,
    /// and never the name that speaker already has.
    nonisolated static func visibleSuggestions(_ all: [NameSuggestion], speakers: [String],
                                               names: [String: String]) -> [NameSuggestion] {
        var seen = Set<String>()
        return all.filter { suggestion in
            speakers.contains(suggestion.label)
                && names[suggestion.label] != suggestion.name
                && seen.insert(suggestion.label).inserted
        }
    }

    /// What VoiceOver reads for a roster chip: the name, its share of the
    /// talking, the side of the call, and where the name came from.
    func speakerAccessibilityLabel(_ label: String) -> String {
        var parts = [name(for: label)]
        if let share = speakerStats.first(where: { $0.label == label })?.share {
            parts.append("\(Int((share * 100).rounded())) percent of the talking")
        }
        if let side = side(for: label) { parts.append(side.accessibilityLabel) }
        if isChannelNamed(label) {
            parts.append("name from your microphone")
        } else if isSuggestedName(label) {
            parts.append("suggested name")
        }
        return parts.joined(separator: ", ")
    }

    /// The name came from an accepted suggestion ("suggested" marker).
    func isSuggestedName(_ label: String) -> Bool {
        SpeakerChannelMarkers.isSuggested(label, sources: speakerNameSources)
    }

    /// Accept: the same PUT as a rename — every other name kept, this
    /// label's set, `sources[label] = "suggestion"`. Undo puts the names
    /// back as they were.
    func accept(_ suggestion: NameSuggestion) async {
        guard jobId != nil, canEditSpeakers else { return }
        let restore = NameRestore(label: suggestion.label, names: givenNames,
                                  sources: speakerNameSources, suggestion: suggestion)
        guard await renameSpeaker(label: suggestion.label, to: suggestion.name, source: .suggestion) else {
            return
        }
        nameSuggestions.removeAll { $0.label == suggestion.label }
        offerUndo(LastSpeakerEdit(editId: "suggestion-\(UUID().uuidString)",
                                  summary: "Named \(suggestion.name)", restore: restore))
        announce("Named \(suggestion.name)")
    }

    private func undoAccept(_ restore: NameRestore, jobId: String) async {
        renamingSpeaker = true
        defer { renamingSpeaker = false }
        do {
            let current = name(for: restore.label)
            let stored = try await api.setSpeakerNames(jobId: jobId, names: restore.names)
            speakerNames = namesAfterSaving(stored)
            speakerNameSources = restore.sources
            lastEdit = nil
            if !nameSuggestions.contains(restore.suggestion) { nameSuggestions.append(restore.suggestion) }
            renameSpeakerInNote(from: current, to: name(for: restore.label))
            announce("Undone")
        } catch {
            actionError = error.localizedDescription
        }
    }

    /// ✕: never offer this name for this speaker again. Gone at once; put
    /// back if the server could not be told.
    func dismiss(_ suggestion: NameSuggestion) async {
        guard let jobId, online else { return }
        let before = nameSuggestions
        nameSuggestions.removeAll { $0 == suggestion }
        do {
            try await api.dismissNameSuggestion(jobId: jobId, label: suggestion.label, name: suggestion.name)
            announce("Suggestion dismissed")
        } catch {
            nameSuggestions = before
            actionError = error.localizedDescription
        }
    }

    /// The turn holding the quote: the one whose segments include the
    /// suggestion's first index, else the one it started in.
    nonisolated static func turnId(for suggestion: NameSuggestion, in turns: [TranscriptTurn]) -> Int? {
        if let first = suggestion.segmentIndices?.first,
           let turn = turns.first(where: { ($0.segmentIndices ?? []).contains(first) }) {
            return turn.id
        }
        guard let start = suggestion.startMs else { return nil }
        return turns.last { $0.startMs <= start }?.id
    }

    /// Tap on the quote: scroll to its turn and highlight it for 2 s.
    func revealTurn(for suggestion: NameSuggestion) {
        guard let id = Self.turnId(for: suggestion, in: turns ?? []) else { return }
        let reveal = TurnReveal(turnId: id)
        revealedTurn = reveal
        let duration = highlightDuration
        Task { [weak self] in
            try? await Task.sleep(for: duration)
            if self?.revealedTurn == reveal { self?.revealedTurn = nil }
        }
    }

    /// The highlighted turn, if any.
    var highlightedTurnId: Int? { revealedTurn?.turnId }

    /// "00:14" — where in the recording the quote was said.
    nonisolated static func suggestionTime(_ suggestion: NameSuggestion) -> String? {
        suggestion.startMs.map { formatElapsed(ms: $0) }
    }

    /// What VoiceOver reads for the suggestion row.
    func suggestionAccessibilityLabel(_ suggestion: NameSuggestion) -> String {
        Self.suggestionAccessibilityLabel(suggestion, speaker: name(for: suggestion.label))
    }

    nonisolated static func suggestionAccessibilityLabel(_ suggestion: NameSuggestion, speaker: String) -> String {
        var text = "\(speaker) is probably \(suggestion.name)."
        if let quote = suggestion.quote, !quote.isEmpty {
            text += " Heard: \(quote)"
            if let time = suggestionTime(suggestion) { text += ", at \(time)" }
            text += "."
        }
        return text
    }

    nonisolated static let relabelBannerText =
        "Speakers were detected with an older method. Re-label? Your speaker names are kept where possible."

    /// "Speakers were detected with an older method." — offered while
    /// nothing else is happening to the speakers and the person has not
    /// closed it here.
    var showsRelabelBanner: Bool {
        Self.showsRelabelBanner(available: relabelAvailable, dismissed: relabelBannerDismissed,
                                relabel: relabel, hasJob: jobId != nil && transcriptError == nil)
    }

    nonisolated static func showsRelabelBanner(available: Bool, dismissed: Bool, relabel: RelabelState,
                                               hasJob: Bool) -> Bool {
        available && !dismissed && relabel == .idle && hasJob
    }

    /// The banner's "Re-label": the Sprint 29 flow, the diarizer counting.
    func relabelFromBanner() async {
        await relabelSpeakers(expected: nil)
    }

    func dismissRelabelBanner() {
        relabelBannerDismissed = true
    }

    private func renameSpeakerInNote(from: String, to: String) {
        guard editable, var next = content, let sections = next.sections else { return }
        next.sections = sections.map { section in
            guard let text = section.text, !text.isEmpty else { return section }
            var copy = section
            copy.text = Self.renameSpeaker(in: text, from: from, to: to)
            return copy
        }
        commit(next)
    }

    /// "Speaker 2: …" → "Olena: …" at the start of lines only — the
    /// from-transcript note puts the name at the head of each turn.
    static func renameSpeaker(in text: String, from: String, to: String) -> String {
        let pattern = "(^|\\n)" + NSRegularExpression.escapedPattern(for: from) + ": "
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return text }
        let template = "$1" + NSRegularExpression.escapedTemplate(for: to) + ": "
        return regex.stringByReplacingMatches(in: text, range: NSRange(text.startIndex..., in: text),
                                              withTemplate: template)
    }

    // MARK: - Ask this note

    /// The server sees the last few turns for context; it caps the thread.
    private static let historyLimit = 12

    func ask(_ question: String) async {
        let text = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !asking else { return }
        askError = nil
        let history = chat.suffix(Self.historyLimit).map { AskTurn(role: $0.role, text: $0.text) }
        chat.append(ChatMessage(role: .user, text: text))
        asking = true
        defer { asking = false }
        do {
            let reply = try await api.askNote(id: noteId, question: text, history: Array(history))
            chat.append(ChatMessage(role: .assistant, text: reply.answer))
        } catch {
            // The question stays in the thread so it can be retried by eye.
            askError = error.localizedDescription
        }
    }

    func clearChat() {
        chat = []
        askError = nil
    }

    // MARK: - Editing (drafts autosave; other states are read-only here)

    func setTitle(_ title: String) {
        guard var next = content else { return }
        next.title = title
        commit(next)
    }

    func setSectionText(_ key: String, _ text: String) {
        guard var next = content else { return }
        var section = next.section(key)
        section.text = text
        next.upsert(section)
        commit(next)
    }

    private func commit(_ next: NoteContent) {
        guard editable, next != content else { return }
        content = next
        pending = (next, version)
        saveState = .dirty
        saveTask?.cancel()
        saveTask = Task { [weak self] in
            try? await Task.sleep(for: Self.autosaveDelay)
            guard !Task.isCancelled else { return }
            await self?.flush()
        }
    }

    /// Write the pending content now.
    func flush() async {
        // Stop the timer. When flush() runs *inside* the timer task this
        // cancels the current task too, and a cancelled task makes
        // URLSession fail with "cancelled" before anything is sent — so the
        // write below runs in its own task, out of reach of that cancellation.
        saveTask?.cancel()
        saveTask = nil
        if let inFlight = saveInFlight { await inFlight.value }
        guard let snapshot = pending else { return }
        pending = nil
        saveState = .saving
        let write = Task { [weak self] in
            guard let self else { return }
            await self.write(snapshot)
        }
        saveInFlight = write
        await write.value
        if saveInFlight == write { saveInFlight = nil }
    }

    private func write(_ snapshot: (content: NoteContent, version: Int)) async {
        do {
            let result = try await api.updateDraft(id: noteId, content: snapshot.content,
                                                   expectedVersion: snapshot.version)
            version = result.versionNumber
            saveState = pending == nil ? .saved : .dirty
        } catch let error as APIError where error.isConflict {
            conflict = true
            saveState = .error
        } catch {
            saveState = .error
            actionError = error.localizedDescription
        }
    }

    /// Fetch the PDF and let the user pick where to keep it.
    func exportPDF() async {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            let data = try await api.notePDF(id: noteId, purpose: readPurpose == nil ? nil : .export)
            let panel = NSSavePanel()
            panel.nameFieldStringValue = "\(note?.code ?? "note").pdf"
            panel.allowedContentTypes = [.pdf]
            panel.canCreateDirectories = true
            NSApp.activate(ignoringOtherApps: true)
            if panel.runModal() == .OK, let url = panel.url {
                try data.write(to: url)
            }
        } catch {
            actionError = error.localizedDescription
        }
    }

    // MARK: - Delete, visibility, sharing (0016)

    func loadSharing() async {
        sharing = try? await api.sharing(id: noteId)
    }

    var isWorkspaceVisible: Bool {
        (sharing?.visibility ?? note?.visibility) == "workspace"
    }

    func setWorkspaceVisible(_ on: Bool) async {
        await sharingAction { try await self.api.setVisibility(id: self.noteId, visibility: on ? "workspace" : "private") }
    }

    /// The public "anyone with the link" URL, creating the link on first use.
    func publicLinkURL(webAppURL: String) async -> URL? {
        if sharing?.publicLink == nil {
            await sharingAction { try await self.api.createPublicLink(id: self.noteId) }
        }
        guard let path = sharing?.publicLink?.path,
              let root = URL(string: webAppURL.trimmingCharacters(in: .whitespaces)) else { return nil }
        return root.appending(path: String(path.dropFirst()))
    }

    func revokePublicLink() async {
        await sharingAction { try await self.api.revokePublicLink(id: self.noteId) }
    }

    // MARK: - Per-recipient links (Sprint 19)

    var recipientLinks: [LinkView] { sharing?.recipientLinks ?? [] }

    /// Sprint 23: the note's sharing view carries the workspace rules.
    var rules: SharingConstraints { sharing?.constraints ?? .permissive }

    /// Mint a link for one recipient and hand back its full URL, or nil
    /// when the call failed (the reason is on `actionError`).
    /// The last link the product mailed from this screen, for the sheet's notice.
    @Published var lastSent: LinkView?

    func createRecipientLink(label: String, email: String, expiresInDays: Int,
                             webAppURL: String, send: Bool = false, message: String = "",
                             source: String = "native") async -> URL? {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            let link = try await api.createLink(id: noteId, label: label,
                                                recipientEmail: email.isEmpty ? nil : email,
                                                expiresInDays: expiresInDays,
                                                mail: send, personalMessage: message, source: source)
            if send { lastSent = link }
            await loadSharing()
            guard let root = URL(string: webAppURL.trimmingCharacters(in: .whitespaces)) else { return nil }
            return root.appending(path: String(link.path.dropFirst()))
        } catch {
            actionError = error.localizedDescription
            return nil
        }
    }

    /// Sprint 22: mail (again). The outcome lands on the link row; a
    /// refusal (opted out, cap) is the error the sheet shows.
    func sendLink(_ link: LinkView, message: String = "") async {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            lastSent = try await api.sendLink(id: noteId, linkId: link.id, personalMessage: message)
            await loadSharing()
        } catch APIError.http(_, let problem) where problem?.code == "recipient_opted_out" {
            actionError = "This recipient asked not to receive e-mails. Copy the link instead."
            await loadSharing()
        } catch {
            actionError = error.localizedDescription
        }
    }

    func revokeLink(_ link: LinkView) async {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            try await api.revokeLink(id: noteId, linkId: link.id)
            await loadSharing()
        } catch {
            actionError = error.localizedDescription
        }
    }


    // MARK: - Action items + recipient responses (Sprint 20)

    @Published private(set) var items: [ActionItem] = []
    @Published private(set) var responses: [ItemResponse] = []

    /// Items are derived from the note text on read. Read-only cache: nothing
    /// user-authored lives here, so nothing can be lost offline.
    func loadItems() async {
        guard isDraft else {
            items = []
            responses = []
            return
        }
        async let i = api.items(noteId: noteId)
        async let r = api.responses(noteId: noteId)
        items = (try? await i) ?? []
        responses = (try? await r) ?? []
    }

    var liveDisputes: Int { responses.filter { $0.kind == .dispute && $0.clearedAt == nil }.count }

    /// Optimistic; reverts on failure.
    func setStatus(_ item: ActionItem, _ status: ActionItemStatus) async {
        guard let idx = items.firstIndex(where: { $0.id == item.id }) else { return }
        let before = items[idx].status
        items[idx].status = status
        actionError = nil
        do {
            items[idx] = try await api.setItemStatus(noteId: noteId, itemId: item.id, status: status)
        } catch {
            items[idx].status = before
            actionError = error.localizedDescription
        }
    }

    func markDone(_ item: ActionItem) async {
        await setStatus(item, item.status == .done ? .open : .done)
    }

    /// One-click sender action: everything confirmed and undisputed is done.
    func markAllConfirmedDone() async {
        for item in items where item.status == .open && item.counts.confirms > 0 && item.counts.disputes == 0 {
            await setStatus(item, .done)
        }
    }

    func clear(_ response: ItemResponse) async {
        let beforeResponses = responses
        let beforeItems = items
        responses.removeAll { $0.id == response.id }
        if let idx = items.firstIndex(where: { $0.itemKey == response.itemKey }) {
            items[idx].responses.removeAll { $0.id == response.id }
            items[idx].counts = ItemCounts(
                confirms: items[idx].counts.confirms - (response.kind == .confirm ? 1 : 0),
                dones: items[idx].counts.dones - (response.kind == .done ? 1 : 0),
                disputes: items[idx].counts.disputes - (response.kind == .dispute ? 1 : 0))
        }
        actionError = nil
        do {
            try await api.clearResponse(noteId: noteId, responseId: response.id)
        } catch {
            responses = beforeResponses
            items = beforeItems
            actionError = error.localizedDescription
        }
    }

    func linkURL(_ link: LinkView, webAppURL: String) -> URL? {
        URL(string: webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: String(link.path.dropFirst()))
    }

    /// Mail the note to the people named, from the server.
    ///
    /// Returns the per-recipient outcomes, or nil when the call itself
    /// failed (the reason is on `actionError`). Members are granted
    /// access as a side effect, so the sharing view is refreshed from
    /// the reply rather than re-fetched.
    func sendShareEmail(recipients: [String], message: String) async -> [ShareEmailOutcome]? {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            let result = try await api.shareByEmail(
                id: noteId,
                recipients: recipients,
                message: message,
                // The sender's language. The recipient's is unknowable —
                // half of them have no account here — and people share
                // within a team.
                lang: Locale.current.language.languageCode?.identifier ?? "en")
            sharing = result.sharing
            return result.results
        } catch {
            actionError = error.localizedDescription
            return nil
        }
    }

    func delete() async {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            try await api.deleteNote(id: noteId)
            deleted = true
        } catch {
            actionError = error.localizedDescription
        }
    }

    private func sharingAction(_ work: () async throws -> SharingView) async {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            sharing = try await work()
        } catch {
            actionError = error.localizedDescription
        }
    }

    /// The note as Markdown, for "Download Markdown".
    func markdown() -> String {
        guard let content else { return "" }
        var lines = ["# \((content.title ?? "").isEmpty ? "Untitled note" : content.title!)", ""]
        if let note {
            lines.append("_\(note.code) · \(note.updatedAt.formatted(date: .abbreviated, time: .shortened))_")
            lines.append("")
        }
        for def in sections {
            let text = (content.section(def.id).text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if text.isEmpty { continue }
            lines.append("## \(def.name)")
            lines.append("")
            lines.append(text)
            lines.append("")
        }
        return lines.joined(separator: "\n")
    }

    func exportMarkdown() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "\(note?.code ?? "note").md"
        panel.canCreateDirectories = true
        NSApp.activate(ignoringOtherApps: true)
        if panel.runModal() == .OK, let url = panel.url {
            try? markdown().write(to: url, atomically: true, encoding: .utf8)
        }
    }

    // MARK: - Copy

    func transcriptText() -> String {
        let diarized = self.diarized
        return (turns ?? []).map { turn in
            let body = turn.paragraphs.joined(separator: "\n")
            return diarized ? "\(displayName(for: turn)): \(body)" : body
        }.joined(separator: "\n\n")
    }
}
