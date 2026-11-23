import Foundation
import LocalAuthentication
import Security
import SystemConfiguration

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
    private static let deviceNameKey = "syncDeviceName"
    /// The service trims a name to this many characters; keep the same limit here.
    static let deviceNameLimit = 60

    /// The hosted sync service ships with the app. Keeping it here means a
    /// fresh install has one less field to get wrong; the pairing code alone
    /// is enough. Existing custom addresses are ignored on purpose.
    static let builtInBaseURL = "https://sync.joycine.xyz"

    /// A stable per-install device id. It is not a secret; it only labels
    /// this device's blob in the space.
    ///
    /// The Keychain item keeps a copy too. Preferences can be lost (a clean
    /// reinstall keeps the Keychain item but not the plist), and the copy then
    /// keeps this Mac the same device instead of a new one whose rows would
    /// count next to the old bucket's.
    static func deviceID() -> String {
        if let existing = UserDefaults.standard.string(forKey: deviceIDKey),
           SyncKeys.isIdentifier(existing) {
            return existing
        }
        if let paired = load()?.deviceID {
            UserDefaults.standard.set(paired, forKey: deviceIDKey)
            return paired
        }
        let fresh = SyncKeys.randomIdentifier()
        UserDefaults.standard.set(fresh, forKey: deviceIDKey)
        return fresh
    }

    /// The name this Mac goes by in the space: the computer name until the
    /// user renames it.
    static func deviceName(in defaults: UserDefaults = .standard) -> String {
        if let saved = defaults.string(forKey: deviceNameKey), !saved.isEmpty { return saved }
        return computerName()
    }

    /// Saves a typed name and returns what the device is called from now on.
    /// An empty name goes back to the computer name.
    @discardableResult
    static func setDeviceName(_ raw: String, in defaults: UserDefaults = .standard) -> String {
        let cleaned = cleanName(raw)
        if cleaned.isEmpty {
            defaults.removeObject(forKey: deviceNameKey)
            return computerName()
        }
        defaults.set(cleaned, forKey: deviceNameKey)
        return cleaned
    }

    /// One line, no control characters, at most `deviceNameLimit` characters.
    static func cleanName(_ raw: String) -> String {
        let line = raw.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
        let printable = String.UnicodeScalarView(line.unicodeScalars.filter { !CharacterSet.controlCharacters.contains($0) })
        return String(String(printable).prefix(deviceNameLimit))
    }

    /// How a device is listed: its name, or a short handle when it has none.
    static func label(name: String, device: String) -> String {
        if !name.isEmpty { return name }
        return "设备 " + device.prefix(8) + "…"
    }

    /// The name the user gave this computer in System Settings.
    static func computerName() -> String {
        if let name = SCDynamicStoreCopyComputerName(nil, nil) as? String,
           !cleanName(name).isEmpty {
            return cleanName(name)
        }
        let host = Host.current().localizedName ?? ProcessInfo.processInfo.hostName
        let cleaned = cleanName(host)
        return cleaned.isEmpty ? "Mac" : cleaned
    }

    static var baseURL: String { builtInBaseURL }

    static func setBaseURL(_ value: String) {
        UserDefaults.standard.set(builtInBaseURL, forKey: baseURLKey)
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
                                 baseURL: builtInBaseURL)
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
