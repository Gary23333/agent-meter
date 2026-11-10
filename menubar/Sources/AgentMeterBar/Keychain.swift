import Foundation
import Security

/// Why a non-interactive Keychain read did not return a session. Kept distinct
/// so startup can log the reason instead of collapsing everything to nil.
enum SessionReadFailure: Error, Equatable {
    /// No item exists for this slot.
    case notFound
    /// The item exists but reading it would need user interaction: the app is
    /// not authorized by the item's access control, or the keychain is locked.
    /// Startup must not prompt; an explicit user "connect" action may.
    case authorizationRequired(OSStatus)
    /// Data was returned but is not a valid session dictionary.
    case invalidData
    /// Any other Security framework error.
    case other(OSStatus)

    /// Maps a SecItemCopyMatching status (queried with interaction disabled).
    static func from(status: OSStatus) -> SessionReadFailure {
        switch status {
        case errSecItemNotFound:
            return .notFound
        case errSecInteractionNotAllowed, errSecInteractionRequired, errSecAuthFailed:
            return .authorizationRequired(status)
        default:
            return .other(status)
        }
    }

    /// For logs only: never contains secret values.
    var logDescription: String {
        switch self {
        case .notFound:
            return "item not found"
        case .authorizationRequired(let status):
            return "not authorized or keychain locked (OSStatus \(status)); skipped at startup, use an explicit connect action to authorize"
        case .invalidData:
            return "stored data is not a valid session"
        case .other(let status):
            return "Security framework error (OSStatus \(status))"
        }
    }
}

/// Website sessions live only in the login Keychain (never in files or
/// UserDefaults) and are handed to the local backend in memory.
enum SessionKeychain {
    private static let service = "local.agent-meter.web-sessions"

    /// Existence check via attributes only: never shows a Keychain prompt.
    static func exists(_ provider: String) -> Bool {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service,
                                    kSecAttrAccount as String: provider,
                                    kSecReturnAttributes as String: true,
                                    kSecMatchLimit as String: kSecMatchLimitOne]
        var item: CFTypeRef?
        return SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess
    }

    /// All saved slots ("qoder", "qoder#2", ...), attributes only: no prompt.
    static func slots() -> [String] {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service,
                                    kSecReturnAttributes as String: true,
                                    kSecMatchLimit as String: kSecMatchLimitAll]
        var items: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &items) == errSecSuccess,
              let list = items as? [[String: Any]] else { return [] }
        return list.compactMap { $0[kSecAttrAccount as String] as? String }
    }

    /// Reads the secret, allowing macOS to prompt for authorization. Only for
    /// explicit user actions (connect / save); callers must stay off the main
    /// thread. Startup uses `loadResult` instead, which never prompts.
    static func load(_ provider: String) -> [String: String]? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service,
                                    kSecAttrAccount as String: provider,
                                    kSecReturnData as String: true,
                                    kSecMatchLimit as String: kSecMatchLimitOne]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess, let data = item as? Data else { return nil }
        return try? JSONDecoder().decode([String: String].self, from: data)
    }

    /// Non-interactive read for startup: interaction is disabled, so this can
    /// never show a Keychain prompt, and the failure reason stays distinguishable.
    static func loadResult(_ provider: String) -> Result<[String: String], SessionReadFailure> {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service,
                                    kSecAttrAccount as String: provider,
                                    kSecReturnData as String: true,
                                    kSecMatchLimit as String: kSecMatchLimitOne,
                                    kSecUseAuthenticationUI as String: kSecUseAuthenticationUIFail]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess else { return .failure(.from(status: status)) }
        guard let data = item as? Data,
              let session = try? JSONDecoder().decode([String: String].self, from: data) else {
            return .failure(.invalidData)
        }
        return .success(session)
    }

    /// What `save` should do after its update-first attempt. Pure decision so
    /// the branch logic stays testable without touching the real Keychain.
    enum UpdateOutcome: Equatable {
        case updated
        case addNewItem
        case failed(OSStatus)
    }

    static func updateOutcome(forStatus status: OSStatus) -> UpdateOutcome {
        switch status {
        case errSecSuccess: return .updated
        case errSecItemNotFound: return .addNewItem
        default: return .failed(status)
        }
    }

    /// Updates the value in place so the item's access control (and existing
    /// "Always Allow" grants) survive rebuilds; only a missing item is added.
    /// No access-control relaxation: new items keep the default per-app ACL.
    @discardableResult
    static func save(_ provider: String, _ session: [String: String]) -> Bool {
        guard let data = try? JSONEncoder().encode(session) else { return false }
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service,
                                    kSecAttrAccount as String: provider]
        let valueUpdate: [String: Any] = [kSecValueData as String: data]
        switch updateOutcome(forStatus: SecItemUpdate(query as CFDictionary, valueUpdate as CFDictionary)) {
        case .updated:
            return true
        case .failed(let status):
            NSLog("AgentMeterBar keychain: update failed for slot %@ (OSStatus %d)", provider, status)
            return false
        case .addNewItem:
            break
        }
        var attributes = query
        attributes[kSecAttrLabel as String] = "Agent 用量 · \(provider) 网页登录"
        attributes[kSecValueData as String] = data
        let addStatus = SecItemAdd(attributes as CFDictionary, nil)
        if addStatus == errSecDuplicateItem {
            // A concurrent writer created the item in between: update in place.
            return SecItemUpdate(query as CFDictionary, valueUpdate as CFDictionary) == errSecSuccess
        }
        if addStatus != errSecSuccess {
            NSLog("AgentMeterBar keychain: add failed for slot %@ (OSStatus %d)", provider, addStatus)
        }
        return addStatus == errSecSuccess
    }

    static func delete(_ provider: String) {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service,
                                    kSecAttrAccount as String: provider]
        SecItemDelete(query as CFDictionary)
    }
}