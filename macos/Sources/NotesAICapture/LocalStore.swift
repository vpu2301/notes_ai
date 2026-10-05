import Foundation

/// Everything this Mac keeps for a signed-in person, filed by identity and workspace
/// (one key per identity per tenant, plus one migration from the old single bucket).
/// A struct over `UserDefaults` so the rules can be tested without the whole app.
struct LocalStore {
    let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    // MARK: - Recents

    func recents(for scope: AppState.LocalScope) -> [RecentCapture] {
        guard let data = defaults.data(forKey: scope.key(AppState.Keys.recents)),
              let recents = try? JSONDecoder().decode([RecentCapture].self, from: data)
        else { return [] }
        return recents
    }

    func setRecents(_ recents: [RecentCapture], for scope: AppState.LocalScope) {
        guard let data = try? JSONEncoder().encode(recents) else { return }
        defaults.set(data, forKey: scope.key(AppState.Keys.recents))
    }

    /// Add one meeting to a workspace that is not the one on screen (an upload finishing after a switch).
    func addRecent(_ recent: RecentCapture, to scope: AppState.LocalScope, limit: Int = 10) {
        var list = recents(for: scope)
        list.removeAll { $0.jobId == recent.jobId }
        list.insert(recent, at: 0)
        setRecents(Array(list.prefix(limit)), for: scope)
    }

    // MARK: - The one-time move

    /// Move the pre-scoped keys under the first identity that signs in. Runs once
    /// (`localStateMigratedV2`); values are copied, not moved, so a downgrade still finds them.
    @discardableResult
    func migrateLegacyRecents(into scope: AppState.LocalScope) -> Bool {
        guard !defaults.bool(forKey: AppState.Keys.migratedV2) else { return false }
        defaults.set(true, forKey: AppState.Keys.migratedV2)
        guard let legacy = defaults.data(forKey: AppState.Keys.recents),
              defaults.data(forKey: scope.key(AppState.Keys.recents)) == nil
        else { return false }
        defaults.set(legacy, forKey: scope.key(AppState.Keys.recents))
        return true
    }

    // MARK: - Who has data here

    var knownIdentities: [String: String] {
        (try? JSONDecoder().decode(
            [String: String].self,
            from: defaults.data(forKey: AppState.Keys.knownIdentities) ?? Data()))
            ?? [:]
    }

    var lastIdentity: AppState.LastIdentity? {
        guard let data = defaults.data(forKey: AppState.Keys.lastIdentity) else { return nil }
        return try? JSONDecoder().decode(AppState.LastIdentity.self, from: data)
    }

    func remember(identityId: String, email: String, tenantId: String) {
        var known = knownIdentities
        known[identityId] = email
        write(known, forKey: AppState.Keys.knownIdentities)
        write(AppState.LastIdentity(identityId: identityId, email: email, tenantId: tenantId),
              forKey: AppState.Keys.lastIdentity)
    }

    /// Identities with local state here, other than `current`.
    func otherIdentities(besides current: String) -> [(id: String, email: String)] {
        knownIdentities
            .filter { $0.key != current }
            .map { (id: $0.key, email: $0.value) }
            .sorted { $0.email < $1.email }
    }

    /// Delete one identity's local state (scoped keys, pending recordings, list entry). Local only; recordings go because the person asked.
    func removeLocalData(identityId: String, pendingDirectory: URL = PendingCaptures.directory) {
        for key in defaults.dictionaryRepresentation().keys where key.contains(".\(identityId).") {
            defaults.removeObject(forKey: key)
        }
        for capture in PendingCaptures.all(in: pendingDirectory)
        where capture.info.identityId == identityId {
            PendingCaptures.remove(capture)
        }
        var known = knownIdentities
        known[identityId] = nil
        write(known, forKey: AppState.Keys.knownIdentities)
        if lastIdentity?.identityId == identityId {
            defaults.removeObject(forKey: AppState.Keys.lastIdentity)
        }
    }

    private func write<T: Encodable>(_ value: T, forKey key: String) {
        if let data = try? JSONEncoder().encode(value) {
            defaults.set(data, forKey: key)
        }
    }
}
