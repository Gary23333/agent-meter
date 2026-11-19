import CryptoKit
import Foundation

/// Errors the sync layer reports. The codes stay stable so the UI can
/// translate them; nothing here carries a server response body.
enum SyncError: Error, Equatable {
    case notConfigured
    case unauthorized
    case notFound
    case rejected(String)
    case invalidResponse
    case transport(String)
    case cryptoFailed
}

/// The device-independent settings the sync carries.
///
/// Per-device switches (which sources are on, low-resource mode, project
/// aliases) stay local: they are true of one computer and false of another.
struct SyncSettings {
    var theme: String?
    var lowQuotaThreshold: Double?
    var sourceOrder: [String]?
    var claimTime: String?
    var alertsEnabled: Bool?

    var payload: [String: Any] {
        var out: [String: Any] = [:]
        if let theme { out["theme"] = theme }
        if let lowQuotaThreshold { out["low_quota_threshold"] = lowQuotaThreshold }
        if let sourceOrder { out["source_order"] = sourceOrder }
        if let claimTime { out["claim_time"] = claimTime }
        if let alertsEnabled { out["alerts_enabled"] = alertsEnabled }
        return out
    }
}

/// Key material for one sync space.
///
/// The master key never leaves the device. Every blob the service stores is
/// sealed with a key derived from it, so the service cannot read what it keeps
/// and the operator of the service learns nothing about the user's agents.
struct SyncKeys {
    let masterKey: Data
    let spaceID: String

    private static let saltLabel = Data("agentmeter-sync-salt-v1".utf8)
    private static let encryptionInfo = Data("agentmeter-sync-enc-v1".utf8)
    private static let authLabel = Data("agentmeter-auth-v1:".utf8)

    init(masterKey: Data, spaceID: String) throws {
        guard masterKey.count == 32 else { throw SyncError.notConfigured }
        guard SyncKeys.isIdentifier(spaceID) else { throw SyncError.notConfigured }
        self.masterKey = masterKey
        self.spaceID = spaceID
    }

    /// 32 lowercase ASCII hex characters: the only identifier shape the
    /// service takes. Full-width digits are not hex to the server.
    static func isIdentifier(_ value: String) -> Bool {
        let bytes = Array(value.utf8)
        guard bytes.count == 32 else { return false }
        return bytes.allSatisfy { byte in
            (byte >= 48 && byte <= 57) || (byte >= 97 && byte <= 102)
        }
    }

    static func randomIdentifier() -> String {
        let bytes = (0..<16).map { _ in UInt8.random(in: 0...255) }
        return bytes.map { String(format: "%02x", $0) }.joined()
    }

    static func randomMasterKey() -> Data {
        Data((0..<32).map { _ in UInt8.random(in: 0...255) })
    }

    /// The HKDF salt is public. It only keeps this space separate from other
    /// uses of the same master key.
    var salt: Data {
        var hasher = SHA256()
        hasher.update(data: SyncKeys.saltLabel)
        hasher.update(data: Data(spaceID.utf8))
        return Data(hasher.finalize())
    }

    var encryptionKey: SymmetricKey {
        HKDF<SHA256>.deriveKey(inputKeyMaterial: SymmetricKey(data: masterKey),
                                salt: salt,
                                info: SyncKeys.encryptionInfo,
                                outputByteCount: 32)
    }

    /// Bearer token for the service. It is scoped to this space, so a token
    /// that leaks opens this space and no other.
    var authToken: String {
        var message = SyncKeys.authLabel
        message.append(contentsOf: Data(spaceID.utf8))
        let code = HMAC<SHA256>.authenticationCode(for: message,
                                                  using: SymmetricKey(data: masterKey))
        return Data(code).base64EncodedString()
    }

    /// What the service stores instead of the token itself.
    var authHash: String {
        SHA256.hash(data: Data(authToken.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    func seal(_ plaintext: Data) throws -> Data {
        do {
            return try ChaChaPoly.seal(plaintext, using: encryptionKey).combined
        } catch {
            throw SyncError.cryptoFailed
        }
    }

    func open(_ ciphertext: Data) throws -> Data {
        do {
            let box = try ChaChaPoly.SealedBox(combined: ciphertext)
            return try ChaChaPoly.open(box, using: encryptionKey)
        } catch {
            throw SyncError.cryptoFailed
        }
    }
}

/// What the service knows about one device's blob.
struct SyncDeviceManifest: Equatable {
    let deviceID: String
    let size: Int
    let version: Int
    let updatedAt: Date
}

/// The remote service, as the runner sees it. A protocol so a full round can
/// be tested without a network.
protocol SyncTransport {
    func manifest(spaceID: String, token: String) async throws -> [SyncDeviceManifest]
    func put(spaceID: String, deviceID: String, token: String, ciphertext: Data) async throws
    func blob(spaceID: String, deviceID: String, token: String) async throws -> Data
    func delete(spaceID: String, deviceID: String, token: String) async throws
}

/// HTTP transport for the sync service.
///
/// Separate from `BackendClient` on purpose: this one leaves the machine, so
/// it gets its own session, its own base URL and its own bearer token.
struct SyncService: SyncTransport {
    let baseURL: URL
    private let session: URLSession

    /// Plain http is only allowed on loopback: the payload and the bearer
    /// token must never travel in the clear.
    init(baseURL: URL) throws {
        let scheme = baseURL.scheme?.lowercased() ?? ""
        let host = baseURL.host?.lowercased() ?? ""
        let loopback = host == "127.0.0.1" || host == "localhost" || host == "::1"
        guard scheme == "https" || (scheme == "http" && loopback) else {
            throw SyncError.notConfigured
        }
        self.baseURL = baseURL
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 30
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        self.session = URLSession(configuration: configuration)
    }

    private func url(_ path: String) -> URL {
        baseURL.appendingPathComponent(path)
    }

    /// Creates the space. The client generates the id, so it can derive the
    /// token before the space exists.
    func createSpace(spaceID: String, token: String, authHash: String) async throws -> String {
        var request = URLRequest(url: url("v1/sync/spaces"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["space_id": spaceID,
                                                                      "auth_hash": authHash])
        let (data, _) = try await send(request)
        guard let space = decodeObject(data)?["space_id"].string else { throw SyncError.invalidResponse }
        return space
    }

    func manifest(spaceID: String, token: String) async throws -> [SyncDeviceManifest] {
        var request = URLRequest(url: url("v1/sync/\(spaceID)"))
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        let (data, _) = try await send(request)
        guard let object = decodeObject(data) else { throw SyncError.invalidResponse }
        return object["devices"].array.compactMap { entry in
            guard let id = entry["device_id"].string, let size = entry["size"].double,
                  let version = entry["version"].double else { return nil }
            let updated = entry["updated_at"].double.map { Date(timeIntervalSince1970: $0) } ?? Date()
            return SyncDeviceManifest(deviceID: id, size: Int(size), version: Int(version), updatedAt: updated)
        }
    }

    func put(spaceID: String, deviceID: String, token: String, ciphertext: Data) async throws {
        var request = URLRequest(url: url("v1/sync/\(spaceID)/\(deviceID)"))
        request.httpMethod = "PUT"
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        request.httpBody = ciphertext
        _ = try await send(request)
    }

    func blob(spaceID: String, deviceID: String, token: String) async throws -> Data {
        var request = URLRequest(url: url("v1/sync/\(spaceID)/\(deviceID)"))
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        let (data, _) = try await send(request)
        return data
    }

    func delete(spaceID: String, deviceID: String, token: String) async throws {
        var request = URLRequest(url: url("v1/sync/\(spaceID)/\(deviceID)"))
        request.httpMethod = "DELETE"
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        _ = try await send(request)
    }

    private func decodeObject(_ data: Data) -> JSON? {
        try? JSONDecoder().decode(JSON.self, from: data)
    }

    private func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let data: Data, response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            // Never surface the transport's own text: it can carry a URL.
            throw SyncError.transport("connection_failed")
        }
        guard let http = response as? HTTPURLResponse else { throw SyncError.invalidResponse }
        switch http.statusCode {
        case 200...299:
            return (data, http)
        case 401, 403:
            throw SyncError.unauthorized
        case 404:
            throw SyncError.notFound
        default:
            let code = decodeObject(data)?["error"].string ?? "http_\(http.statusCode)"
            throw SyncError.rejected(code)
        }
    }
}

/// The loopback backend, as the sync layer sees it. A protocol so the round
/// can be tested without a running backend.
protocol SyncBackend {
    /// The redacted payload this device may upload, as raw JSON bytes.
    func syncPayload(localDevice: String, settings: SyncSettings) async throws -> Data
    /// Hands a payload decrypted from the service to the backend.
    func importSync(localDevice: String, payload: Data) async throws
}

/// What one sync round did.
struct SyncReport: Equatable {
    var uploaded = false
    var importedDevices: [String] = []
    /// Devices whose blob could not be read or handed over. One bad blob
    /// must not cost the whole round.
    var failedDevices: [String] = []
    var devices = 0
}

/// Drives one sync round: seal the local payload, upload it, then open every
/// other device's blob and hand it to the backend.
struct SyncRunner {
    let transport: any SyncTransport
    let keys: SyncKeys
    let deviceID: String

    /// Uploads this device's payload. The service only ever sees ciphertext.
    func upload(_ payload: Data) async throws {
        let sealed = try keys.seal(payload)
        try await transport.put(spaceID: keys.spaceID, deviceID: deviceID,
                                token: keys.authToken, ciphertext: sealed)
    }

    /// Opens the other devices' blobs. A blob that will not open is reported
    /// and skipped, not fatal.
    func remotePayloads(from manifest: [SyncDeviceManifest]) async throws -> [String: Data] {
        var out: [String: Data] = [:]
        for entry in manifest where entry.deviceID != deviceID {
            do {
                let sealed = try await transport.blob(spaceID: keys.spaceID, deviceID: entry.deviceID,
                                                      token: keys.authToken)
                out[entry.deviceID] = try keys.open(sealed)
            } catch {
                continue
            }
        }
        return out
    }

    /// The devices that have a blob in this space.
    func devices() async throws -> [SyncDeviceManifest] {
        try await transport.manifest(spaceID: keys.spaceID, token: keys.authToken)
    }
}

/// Ties the loopback backend and the remote service into one round.
struct SyncCoordinator {
    let backend: any SyncBackend
    let runner: SyncRunner
    var settings = SyncSettings()

    /// One full round: upload, then pull every other device's payload.
    func run() async throws -> SyncReport {
        var report = SyncReport()
        let payload = try await backend.syncPayload(localDevice: runner.deviceID, settings: settings)
        try await runner.upload(payload)
        report.uploaded = true
        // One manifest read for the whole round.
        let manifest = try await runner.devices()
        report.devices = manifest.count
        let payloads = try await runner.remotePayloads(from: manifest)
        for device in manifest.map(\.deviceID).sorted() where device != runner.deviceID {
            guard let plain = payloads[device] else {
                report.failedDevices.append(device)
                continue
            }
            do {
                try await backend.importSync(localDevice: runner.deviceID, payload: plain)
                report.importedDevices.append(device)
            } catch {
                report.failedDevices.append(device)
            }
        }
        return report
    }
}
