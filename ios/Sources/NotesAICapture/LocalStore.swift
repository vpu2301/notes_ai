import Foundation

/// Whose data this is: one identity, in one workspace.
///
/// Everything this app keeps on the phone that came from the server is
/// scoped to both. The identity because a phone can be handed to a
/// colleague, and the workspace because one identity can be in several —
/// a meeting recorded for the agency must not appear in the list while
/// the client's workspace is open, even as a title.
///
/// The scope is a key suffix rather than a separate container: UserDefaults
/// is what this app already uses, and a suffix is something you can look at
/// in a dump and understand.
struct StateScope: Hashable, Sendable {
    let identityId: String
    let tenantId: String

    /// `.<identity>.<tenant>` — appended to the unscoped key.
    var suffix: String { ".\(identityId).\(tenantId)" }

    func key(_ base: String) -> String { base + suffix }

    /// Signed out, or signed in to nothing: there is no scope to write in,
    /// and nothing should be written.
    static func of(identityId: String, tenantId: String?) -> StateScope? {
        guard !identityId.isEmpty, let tenantId, !tenantId.isEmpty else { return nil }
        return StateScope(identityId: identityId, tenantId: tenantId)
    }
}

/// Reading and writing per-scope values in UserDefaults.
///
/// The unscoped keys are still there and still device-wide, which is
/// right for what is left in them: the backend URLs, the theme, the
/// capture language. None of those is anybody's data.
enum ScopedDefaults {
    /// Keys that are scoped. Named here so the migration, the enumeration
    /// and the "remove other accounts' data" button cannot drift apart.
    static let scopedKeys = ["recentCaptures"]

    static func decode<T: Decodable>(_ type: T.Type, _ base: String, in scope: StateScope,
                                     from defaults: UserDefaults = .standard) -> T? {
        guard let data = defaults.data(forKey: scope.key(base)) else { return nil }
        return try? JSONDecoder().decode(type, from: data)
    }

    static func encode<T: Encodable>(_ value: T, _ base: String, in scope: StateScope,
                                     to defaults: UserDefaults = .standard) {
        guard let data = try? JSONEncoder().encode(value) else { return }
        defaults.set(data, forKey: scope.key(base))
    }

    static func remove(_ base: String, in scope: StateScope,
                       from defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: scope.key(base))
    }

    /// Every scope that has anything stored under it, whoever it belongs
    /// to. Used by Settings to offer removing the data of accounts that
    /// are no longer signed in here.
    static func allScopes(in defaults: UserDefaults = .standard) -> Set<StateScope> {
        var found: Set<StateScope> = []
        for key in defaults.dictionaryRepresentation().keys {
            for base in scopedKeys where key.hasPrefix(base + ".") {
                let parts = key.dropFirst(base.count + 1).split(separator: ".", maxSplits: 1)
                guard parts.count == 2 else { continue }
                found.insert(StateScope(identityId: String(parts[0]), tenantId: String(parts[1])))
            }
        }
        return found
    }

    /// Everything stored for one identity, across its workspaces.
    static func scopes(ofIdentity identityId: String,
                       in defaults: UserDefaults = .standard) -> Set<StateScope> {
        allScopes(in: defaults).filter { $0.identityId == identityId }
    }

    static func removeAll(for scope: StateScope, from defaults: UserDefaults = .standard) {
        for base in scopedKeys { defaults.removeObject(forKey: scope.key(base)) }
    }

    // MARK: - The keys this app used to write

    static let migrationKey = "stateScopeMigrationV1"

    /// Move the pre-IDX-I2 unscoped values into the first scope that signs
    /// in, once.
    ///
    /// The alternative — leaving them where they are and starting empty —
    /// would look to the person like the app had forgotten every meeting
    /// they had recorded, which is a poor way to introduce a feature they
    /// did not ask for. The first identity to sign in after the update is
    /// almost always the one whose data it is: the app could only ever
    /// hold one account's before.
    @discardableResult
    static func migrateLegacy(into scope: StateScope,
                              defaults: UserDefaults = .standard) -> Bool {
        guard !defaults.bool(forKey: migrationKey) else { return false }
        defaults.set(true, forKey: migrationKey)
        var moved = false
        for base in scopedKeys {
            guard let data = defaults.data(forKey: base) else { continue }
            // Never overwrite: if this scope already has a value, the
            // legacy one is the older of the two.
            if defaults.data(forKey: scope.key(base)) == nil {
                defaults.set(data, forKey: scope.key(base))
                moved = true
            }
            defaults.removeObject(forKey: base)
        }
        return moved
    }
}

/// This phone's captures, per workspace.
///
/// A thin thing on purpose: the interesting part is that it cannot be
/// asked for a list without saying whose, which is what keeps the
/// switcher honest.
struct RecentsStore {
    static let key = "recentCaptures"
    /// How many are kept. Older ones are on the server anyway.
    static let limit = 10

    let scope: StateScope
    var defaults: UserDefaults = .standard

    func load() -> [RecentCapture] {
        ScopedDefaults.decode([RecentCapture].self, Self.key, in: scope, from: defaults) ?? []
    }

    func save(_ recents: [RecentCapture]) {
        ScopedDefaults.encode(Array(recents.prefix(Self.limit)), Self.key, in: scope, to: defaults)
    }
}
