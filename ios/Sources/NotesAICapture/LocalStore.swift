import Foundation

/// Whose data this is: one identity, in one workspace. Everything local from
/// the server is scoped to both (a title from another workspace is a leak). A key suffix in UserDefaults.
struct StateScope: Hashable, Sendable {
    let identityId: String
    let tenantId: String

    /// `.<identity>.<tenant>` — appended to the unscoped key.
    var suffix: String { ".\(identityId).\(tenantId)" }

    func key(_ base: String) -> String { base + suffix }

    /// Signed out, or signed in to nothing: nothing should be written.
    static func of(identityId: String, tenantId: String?) -> StateScope? {
        guard !identityId.isEmpty, let tenantId, !tenantId.isEmpty else { return nil }
        return StateScope(identityId: identityId, tenantId: tenantId)
    }
}

/// Per-scope values in UserDefaults; unscoped keys stay device-wide (URLs, theme, language).
enum ScopedDefaults {
    /// Keys that are scoped, in one place so migration, enumeration and removal agree.
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

    /// Every scope with anything stored under it, whoever it belongs to.
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

    /// Move the legacy unscoped values into the first scope that signs in, once.
    @discardableResult
    static func migrateLegacy(into scope: StateScope,
                              defaults: UserDefaults = .standard) -> Bool {
        guard !defaults.bool(forKey: migrationKey) else { return false }
        defaults.set(true, forKey: migrationKey)
        var moved = false
        for base in scopedKeys {
            guard let data = defaults.data(forKey: base) else { continue }
            // Never overwrite: the legacy value is the older of the two.
            if defaults.data(forKey: scope.key(base)) == nil {
                defaults.set(data, forKey: scope.key(base))
                moved = true
            }
            defaults.removeObject(forKey: base)
        }
        return moved
    }
}

/// This phone's captures, per workspace: no list without saying whose.
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
