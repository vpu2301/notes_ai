import Foundation

/// The recordings that never reached the server, and what can be done
/// about them.
///
/// IDX-M1 made the app stop deleting them; this is where they become
/// something the person can act on. The rule the whole file is built
/// around: **nothing here deletes a recording that the server has not
/// taken**. Not a failed retry, not a lost membership, not a sign-out —
/// only an upload the server confirmed, or the person saying so.
/// What `PendingUploads` needs from the rest of the app.
///
/// A protocol rather than a reference to `AppState` because the rules
/// here — send, keep, never delete without confirmation — are the ones
/// worth testing, and testing them should not require an `EventKit`
/// service, a Keychain and a live session.
@MainActor
protocol PendingUploadsHost: AnyObject {
    var api: APIClient { get }
    /// Signed in, and the server is reachable.
    var canSendUploads: Bool { get }
    /// Whose recordings this Mac should be showing.
    var uploadIdentityId: String { get }
    func workspaceName(_ tenantId: String?) -> String
    func uploaded(job: TranscriptionJob, capture: PendingCapture) async
    func workspaceLost(_ loss: WorkspaceLoss, tenantId: String) async
}

@MainActor
final class PendingUploads: ObservableObject {
    /// One kept recording plus whatever this Mac is currently doing to it.
    struct Row: Identifiable, Equatable {
        let capture: PendingCapture
        var state: State = .waiting

        var id: String { capture.id }
        var title: String { capture.info.title }
    }

    enum State: Equatable {
        case waiting
        case uploading
        /// The last attempt failed; the recording is untouched.
        case failed(String)
        /// The workspace this was recorded in is no longer reachable, so
        /// there is nowhere to send it until the person picks another.
        case needsWorkspace(String)
    }

    @Published private(set) var rows: [Row] = []
    /// True while a retry pass is running, so the view can say so once
    /// rather than once per row.
    @Published private(set) var isRetrying = false

    private unowned let host: PendingUploadsHost
    /// Where the files are. Its own property so a test can point at a
    /// scratch directory instead of the real Application Support.
    private let directory: URL

    init(host: PendingUploadsHost, directory: URL = PendingCaptures.directory) {
        self.host = host
        self.directory = directory
        reload()
    }

    /// Re-read the directory. Cheap, and the only source of truth: a file
    /// the user moved or deleted in Finder is simply gone.
    func reload() {
        let identity = host.uploadIdentityId
        let kept = PendingCaptures.all(in: directory).filter {
            identity.isEmpty || $0.info.identityId.isEmpty || $0.info.identityId == identity
        }
        let states = Dictionary(uniqueKeysWithValues: rows.map { ($0.id, $0.state) })
        rows = kept.map { Row(capture: $0, state: states[$0.id] ?? .waiting) }
    }

    var isEmpty: Bool { rows.isEmpty }

    // MARK: - Sending

    /// Try everything that is waiting, oldest first.
    ///
    /// Called after a sign-in and after reconnecting; never on a timer, so
    /// a Mac that is offline for a week does not spend the week retrying.
    func retryAll() async {
        guard host.canSendUploads, !isRetrying else { return }
        isRetrying = true
        defer { isRetrying = false }
        for row in rows.sorted(by: { $0.capture.info.recordedAt < $1.capture.info.recordedAt })
        where row.state == .waiting {
            await retry(row.capture)
        }
    }

    /// Send one recording to the workspace its sidecar names.
    func retry(_ capture: PendingCapture) async {
        guard host.canSendUploads else { return }
        setState(.uploading, for: capture)
        let tenantId = capture.info.tenantId
        do {
            let job = try await host.api.submitJob(
                fileURL: capture.audioURL,
                contentType: contentType(for: capture),
                language: capture.info.language,
                diarize: capture.info.diarize,
                tenant: tenantId)
            // The server has the audio now — and only now is the local copy
            // redundant.
            PendingCaptures.remove(capture)
            await host.uploaded(job: job, capture: capture)
            reload()
        } catch let error as APIError {
            if let loss = WorkspaceLoss(code: error.code) {
                // The workspace is gone, not the recording. Say which, and
                // offer the two repairs: another workspace, or a file.
                setState(.needsWorkspace(loss.message(workspace: host.workspaceName(tenantId))),
                         for: capture)
                if let tenantId {
                    await host.workspaceLost(loss, tenantId: tenantId)
                }
            } else {
                setState(.failed(AuthCopy.message(for: error)), for: capture)
            }
        } catch {
            setState(.failed(error.localizedDescription), for: capture)
        }
    }

    /// Point a recording at another workspace and try again.
    func retarget(_ capture: PendingCapture, to tenantId: String) async {
        guard let moved = PendingCaptures.retarget(capture, to: tenantId) else {
            setState(.failed("Could not update the recording's workspace."), for: capture)
            return
        }
        reload()
        setState(.waiting, for: moved)
        await retry(moved)
    }

    // MARK: - The two things only the person may do

    func export(_ capture: PendingCapture, to destination: URL) {
        do {
            try PendingCaptures.export(capture, to: destination)
        } catch {
            setState(.failed("Could not export: \(error.localizedDescription)"), for: capture)
        }
    }

    func delete(_ capture: PendingCapture) {
        PendingCaptures.remove(capture)
        reload()
    }

    func deleteAll() {
        for row in rows { PendingCaptures.remove(row.capture) }
        reload()
    }

    // MARK: - Helpers

    private func contentType(for capture: PendingCapture) -> String {
        switch capture.audioURL.pathExtension.lowercased() {
        case "flac": return "audio/flac"
        case "wav": return "audio/wav"
        case "m4a", "mp4": return "audio/mp4"
        default: return "application/octet-stream"
        }
    }

    private func setState(_ state: State, for capture: PendingCapture) {
        guard let index = rows.firstIndex(where: { $0.id == capture.id }) else { return }
        rows[index].state = state
    }
}
