import Foundation
import Security

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

    /// Reads the secret. After a rebuild macOS may ask the user first, so
    /// callers must stay off the main thread.
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

    @discardableResult
    static func save(_ provider: String, _ session: [String: String]) -> Bool {
        guard let data = try? JSONEncoder().encode(session) else { return false }
        delete(provider)
        let attributes: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                         kSecAttrService as String: service,
                                         kSecAttrAccount as String: provider,
                                         kSecAttrLabel as String: "Agent 用量 · \(provider) 网页登录",
                                         kSecValueData as String: data]
        return SecItemAdd(attributes as CFDictionary, nil) == errSecSuccess
    }

    static func delete(_ provider: String) {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service,
                                    kSecAttrAccount as String: provider]
        SecItemDelete(query as CFDictionary)
    }
}
