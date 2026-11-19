import Foundation
import LocalAuthentication
import Security

/// What this Mac keeps after pairing. The master key lives in the login
/// Keychain, never in UserDefaults and never on the service.
struct SyncConfiguration: Equatable {
    let spaceID: String
    let deviceID: String
    let masterKey: Data
    let baseURL: String

    var shortenedSpace: String { String(spaceID.prefix(8)) }
    var shortenedDevice: String { String(deviceID.prefix(8)) }
}

/// Reads and writes the one sync space this device belongs to.
enum SyncConfigurationStore {
    private static let service = "local.agent-meter.sync"
    private static let account = "space"
    private static let baseURLKey = "syncBaseURL"
    private static let deviceIDKey = "syncDeviceID"

    /// A stable per-install device id. It is not a secret; it only labels
    /// this device's blob in the space.
    static func deviceID() -> String {
        if let existing = UserDefaults.standard.string(forKey: deviceIDKey),
           SyncKeys.isIdentifier(existing) {
            return existing
        }
        let fresh = SyncKeys.randomIdentifier()
        UserDefaults.standard.set(fresh, forKey: deviceIDKey)
        return fresh
    }

    static var baseURL: String {
        UserDefaults.standard.string(forKey: baseURLKey) ?? ""
    }

    static func setBaseURL(_ value: String) {
        UserDefaults.standard.set(value, forKey: baseURLKey)
    }

    static func load() -> SyncConfiguration? {
        guard let data = read(),
              let stored = try? JSONDecoder().decode(Stored.self, from: data),
              SyncKeys.isIdentifier(stored.space_id),
              SyncKeys.isIdentifier(stored.device_id),
              let master = Data(base64Encoded: stored.master_key),
              master.count == 32 else {
            return nil
        }
        return SyncConfiguration(spaceID: stored.space_id, deviceID: stored.device_id,
                                 masterKey: master,
                                 baseURL: stored.base_url ?? baseURL)
    }

    @discardableResult
    static func save(_ configuration: SyncConfiguration) -> Bool {
        setBaseURL(configuration.baseURL)
        let stored = Stored(space_id: configuration.spaceID,
                            master_key: configuration.masterKey.base64EncodedString(),
                            device_id: configuration.deviceID,
                            base_url: configuration.baseURL)
        guard let data = try? JSONEncoder().encode(stored) else { return false }
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service,
                                    kSecAttrAccount as String: account]
        let update: [String: Any] = [kSecValueData as String: data]
        let status = SecItemUpdate(query as CFDictionary, update as CFDictionary)
        if status == errSecSuccess { return true }
        guard status == errSecItemNotFound else { return false }
        var attributes = query
        attributes[kSecAttrLabel as String] = "Agent 用量 · 多机同步"
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        attributes[kSecValueData as String] = data
        return SecItemAdd(attributes as CFDictionary, nil) == errSecSuccess
    }

    static func clear() {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service,
                                    kSecAttrAccount as String: account]
        SecItemDelete(query as CFDictionary)
    }

    private static func read() -> Data? {
        let context = LAContext()
        context.interactionNotAllowed = true
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service,
                                    kSecAttrAccount as String: account,
                                    kSecReturnData as String: true,
                                    kSecMatchLimit as String: kSecMatchLimitOne,
                                    kSecUseAuthenticationContext as String: context]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess else { return nil }
        return item as? Data
    }

    private struct Stored: Codable {
        let space_id: String
        let master_key: String
        let device_id: String
        let base_url: String?
    }
}
