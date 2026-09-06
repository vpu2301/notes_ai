import Foundation

/// Everything this Mac keeps for a signed-in person, filed by **who** and
/// **which workspace**.
///
/// Before IDX-M2 there was one bucket: a second account signing in on the
/// same Mac saw the first one's meetings, and switching workspace showed
/// the wrong workspace's list. The fix is a key per identity per tenant,
/// and one migration that moves what is already there under whoever signs
/// in first.
///
/// A struct over `UserDefaults` rather than a pile of methods on
/// `AppState` so the rules — what a scope is, what a migration does, what
/// "remove this account's data" removes — can be tested without standing
/// up the whole app.
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

    /// Add one meeting to a workspace that is not the one on screen.
    ///
    /// A recording made in workspace A can finish uploading long after the
    /// person moved to B; it belongs in A's list, and putting it in B's
    /// would be filing somebody's meeting in the wrong company.
    func addRecent(_ recent: RecentCapture, to scope: AppState.LocalScope, limit: Int = 10) {
        var list = recents(for: scope)
        list.removeAll { $0.jobId == recent.jobId }
        list.insert(recent, at: 0)
        setRecents(Array(list.prefix(limit)), for: scope)
    }

    // MARK: - The one-time move

    /// Move the pre-IDX-M2 keys under the first identity that signs in.
    ///
    /// Runs once (`localStateMigratedV2`). The legacy values are copied,
    /// not moved: one release of overlap means a downgrade still finds its
    /// meetings, and the keys go away in the release after this one.
    /// Returns whether anything was carried across.
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

    /// Delete one identity's local state: its scoped keys under every
    /// workspace, its pending recordings, and its entry in the list.
    ///
    /// Local only — nothing on the server is touched, and nothing about
    /// any other account is either. The pending recordings go **because
    /// the person asked**, which is the only reason anything ever deletes
    /// one.
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
