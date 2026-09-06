import XCTest
@testable import NotesAICapture

/// A host that records what the app would have been asked to do.
@MainActor
final class FakeUploadHost: PendingUploadsHost {
    let api: APIClient
    var canSendUploads = true
    var uploadIdentityId = "ada"
    var uploads: [(job: TranscriptionJob, capture: PendingCapture)] = []
    var losses: [(loss: WorkspaceLoss, tenantId: String)] = []
    var names: [String: String] = ["tenant-a": "Acme", "tenant-b": "Beta"]

    init(api: APIClient) { self.api = api }

    func workspaceName(_ tenantId: String?) -> String {
        tenantId.flatMap { names[$0] } ?? "that workspace"
    }

    func uploaded(job: TranscriptionJob, capture: PendingCapture) async {
        uploads.append((job, capture))
    }

    func workspaceLost(_ loss: WorkspaceLoss, tenantId: String) async {
        losses.append((loss, tenantId))
    }
}

/// IDX-M2 — the recordings this Mac is holding. One rule runs through all
/// of it: nothing here deletes a recording the server has not taken.
@MainActor
final class PendingUploadsTests: XCTestCase {
    private var directory: URL!
    private var storage: InMemorySessionStorage!

    override func setUp() async throws {
        directory = FileManager.default.temporaryDirectory
            .appending(path: "pending-uploads-\(UUID().uuidString)")
        storage = InMemorySessionStorage(seed: Fixtures.storedSession())
    }

    override func tearDown() async throws {
        try? FileManager.default.removeItem(at: directory)
    }

    private func makeHost() -> FakeUploadHost {
        FakeUploadHost(api: APIClient(settings: .default,
                                      store: SessionStore(storage: storage),
                                      configuration: StubServer.configuration()))
    }

    @discardableResult
    private func keep(title: String = "Weekly sync", tenant: String? = "tenant-a") throws -> URL {
        let source = FileManager.default.temporaryDirectory
            .appending(path: "\(UUID().uuidString).flac")
        try Data("audio".utf8).write(to: source)
        return PendingCaptures.keep(source, info: PendingCapture.Info(
            title: title, language: "auto", diarize: true, recordedAt: Date(),
            identityId: "ada", tenantId: tenant), in: directory)!
    }

    /// A queued ASR job, as the service answers one. `nonisolated` so the
    /// stub server's `@Sendable` handler can build it.
    nonisolated static func job() -> Data {
        Fixtures.json(["id": "job-1", "status": "queued", "created_at": "2026-09-05T10:00:00Z"])
    }

    /// A workspace-scoped token for whatever `/auth/token` was asked for.
    nonisolated static func workspaceToken(_ request: StubServer.Recorded) -> Data {
        let tenant = request.json()["tenant_id"] as? String ?? "tenant-a"
        return Fixtures.json([
            "access_token": "at-\(tenant)", "expires_in": 900,
            "tenant_id": tenant, "roles": ["member"],
        ])
    }

    // MARK: - Sending

    func testASuccessfulUploadIsTheOnlyThingThatRemovesTheFile() async throws {
        let kept = try keep()
        let host = makeHost()
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh": return (200, Fixtures.authenticated(), [:])
            case "/auth/token": return (200, Self.workspaceToken(request), [:])
            default: return (201, Self.job(), [:])
            }
        }
        let pending = PendingUploads(host: host, directory: directory)

        await pending.retryAll()

        XCTAssertFalse(FileManager.default.fileExists(atPath: kept.path))
        XCTAssertTrue(pending.isEmpty)
        XCTAssertEqual(host.uploads.first?.job.id, "job-1")
        XCTAssertEqual(host.uploads.first?.capture.info.title, "Weekly sync")
    }

    func testAFailedUploadKeepsTheRecordingAndSaysWhy() async throws {
        let kept = try keep()
        let host = makeHost()
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh": return (200, Fixtures.authenticated(), [:])
            case "/auth/token": return (200, Self.workspaceToken(request), [:])
            default: return (503, Fixtures.json(["detail": "the transcriber is down"]), [:])
            }
        }
        let pending = PendingUploads(host: host, directory: directory)

        await pending.retryAll()

        XCTAssertTrue(FileManager.default.fileExists(atPath: kept.path))
        guard case .failed(let message) = pending.rows.first?.state else {
            return XCTFail("expected a failure the person can read")
        }
        XCTAssertTrue(message.contains("not answering"), message)
    }

    func testNothingIsSentWhileOffline() async throws {
        try keep()
        let host = makeHost()
        host.canSendUploads = false
        StubServer.install { _ in (201, Self.job(), [:]) }
        let pending = PendingUploads(host: host, directory: directory)

        await pending.retryAll()

        XCTAssertTrue(StubServer.requests.isEmpty, "an offline Mac does not try")
        XCTAssertEqual(pending.rows.count, 1)
        XCTAssertEqual(pending.rows.first?.state, .waiting)
    }

    // MARK: - The workspace going away

    func testLosingTheWorkspaceLeavesTheRecordingWaitingForANewOne() async throws {
        let kept = try keep()
        let host = makeHost()
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/auth/token":
                return (403, Fixtures.json(["code": "not_a_member", "detail": "no"]), [:])
            default:
                return (201, Self.job(), [:])
            }
        }
        let pending = PendingUploads(host: host, directory: directory)

        await pending.retryAll()

        XCTAssertTrue(FileManager.default.fileExists(atPath: kept.path),
                      "a lost membership is not a reason to destroy a recording")
        guard case .needsWorkspace(let message) = pending.rows.first?.state else {
            return XCTFail("expected the row to say it has nowhere to go")
        }
        XCTAssertTrue(message.contains("Acme"), message)
        XCTAssertEqual(host.losses.first?.loss, .notAMember)
        XCTAssertEqual(host.losses.first?.tenantId, "tenant-a")
    }

    func testRetargetingSendsItSomewhereTheUserStillBelongs() async throws {
        let kept = try keep()
        let host = makeHost()
        let refusals = Counter()
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/auth/token":
                // The first workspace refuses; the second mints.
                let body = request.json()["tenant_id"] as? String
                return body == "tenant-a"
                    ? (403, Fixtures.json(["code": "not_a_member"]), [:])
                    : (200, Self.workspaceToken(request), [:])
            default:
                _ = refusals.next()
                return (201, Self.job(), [:])
            }
        }
        let pending = PendingUploads(host: host, directory: directory)
        await pending.retryAll()
        XCTAssertTrue(FileManager.default.fileExists(atPath: kept.path))

        guard let capture = pending.rows.first?.capture else { return XCTFail("row went missing") }
        await pending.retarget(capture, to: "tenant-b")

        XCTAssertFalse(FileManager.default.fileExists(atPath: kept.path), "it went to tenant-b")
        XCTAssertEqual(host.uploads.count, 1)
        XCTAssertEqual(host.uploads.first?.capture.info.tenantId, "tenant-b")
        let upload = StubServer.requests(to: "/asr/jobs").first
        XCTAssertEqual(upload?.headers["Authorization"], "Bearer at-tenant-b",
                       "sent with the workspace's own token, not the active one")
    }

    // MARK: - The two things only the person may do

    func testExportCopiesAndKeeps() async throws {
        let kept = try keep(title: "Board call")
        let host = makeHost()
        let pending = PendingUploads(host: host, directory: directory)
        let destination = directory.appending(path: "exported.flac")

        pending.export(pending.rows[0].capture, to: destination)

        XCTAssertTrue(FileManager.default.fileExists(atPath: destination.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: kept.path),
                      "exporting is a copy; the original is still the app's to send")
        XCTAssertTrue(PendingCaptures.exportName(pending.rows[0].capture).hasPrefix("Board call"))
    }

    func testDeleteRemovesBothHalves() async throws {
        let kept = try keep()
        let host = makeHost()
        let pending = PendingUploads(host: host, directory: directory)
        let sidecar = pending.rows[0].capture.sidecarURL

        pending.delete(pending.rows[0].capture)

        XCTAssertFalse(FileManager.default.fileExists(atPath: kept.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: sidecar.path))
        XCTAssertTrue(pending.isEmpty)
    }

    func testOnlyThisIdentitysRecordingsAreShown() async throws {
        try keep(title: "Mine")
        let source = FileManager.default.temporaryDirectory.appending(path: "\(UUID().uuidString).flac")
        try Data("audio".utf8).write(to: source)
        PendingCaptures.keep(source, info: PendingCapture.Info(
            title: "Somebody else's", language: "auto", diarize: true, recordedAt: Date(),
            identityId: "grace", tenantId: "tenant-a"), in: directory)

        let pending = PendingUploads(host: makeHost(), directory: directory)

        XCTAssertEqual(pending.rows.map(\.title), ["Mine"])
        XCTAssertEqual(PendingCaptures.count(in: directory), 2, "the other one is still there")
    }
}
