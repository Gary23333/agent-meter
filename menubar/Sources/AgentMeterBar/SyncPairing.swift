import CryptoKit
import Foundation

/// What can go wrong while pairing. Kept separate from `SyncError` because
/// pairing has states a normal sync round does not: a waiting peer, an
/// expired code, a code that was already used.
enum PairingError: Error, Equatable {
    case notConfigured
    case unauthorized
    case notFound
    case expired
    case rejected(String)
    case invalidResponse
    case transport(String)
    case cryptoFailed
    case invalidCode
}

/// A six digit code, handled as ASCII digits only. The service never sees
/// the code itself, only its hash.
enum PairingCode {
    static func normalize(_ raw: String) -> String? {
        let digits = raw.unicodeScalars.filter { (48...57).contains(Int($0.value)) }
        guard digits.count == 6 else { return nil }
        return String(String.UnicodeScalarView(digits))
    }

    static func isValid(_ code: String) -> Bool {
        normalize(code) == code
    }

    static func grouped(_ code: String) -> String {
        guard code.count == 6 else { return code }
        return String(code.prefix(3)) + " " + String(code.suffix(3))
    }
}

/// Unpadded base64url, the only shape the service stores.
enum PairingBase64URL {
    static func encode(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    static func decode(_ value: String) -> Data? {
        var standard = value
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let remainder = standard.count % 4
        if remainder > 0 {
            standard += String(repeating: "=", count: 4 - remainder)
        }
        return Data(base64Encoded: standard)
    }
}

/// The public half of one pairing slot, shown once by the first device.
struct PairingSlot: Equatable {
    let slotID: String
    let code: String
    let expiresAt: Date
}

/// What the joining device gets from the code. It contains no key material:
/// only the first device's ephemeral public key and a one-slot token.
struct PairingLookup: Equatable {
    let slotID: String
    let spaceID: String
    let publicKeyA: Data
    let joinToken: String
    let expiresAt: Date
    let attemptsLeft: Int
}

/// What the first device sees while it waits for the second one.
struct PairingSlotState: Equatable {
    let ready: Bool
    let publicKeyB: Data?
    let ciphertext: Data?
    let expiresAt: Date
}

/// What the joining device sees while it waits for the sealed master key.
struct PairingSealedState: Equatable {
    let ready: Bool
    let spaceID: String?
    let ciphertext: Data?
    let expiresAt: Date
}

/// One invitation held in memory on the first device. The private key and
/// the master key never leave this process.
struct PairingInvitation {
    let slot: PairingSlot
    let spaceID: String
    let masterKey: Data
    let privateKey: Curve25519.KeyAgreement.PrivateKey
}

/// The first device's state after it looks at the slot.
enum PairingFinish: Equatable {
    case waiting(expiresAt: Date)
    case sealed(sas: String)
}

/// The joining device's state after it looks for the sealed key.
enum PairingReceive: Equatable {
    case waiting(expiresAt: Date)
    case joined(spaceID: String, masterKey: Data, sas: String)
}

/// X25519, HKDF and ChaChaPoly, with nothing shared in the clear.
enum PairingCrypto {
    private static let wrapInfo = Data("agentmeter-pair-wrap-v1".utf8)
    private static let sasInfo = Data("agentmeter-pair-sas-v1".utf8)

    static func newKeyPair() -> Curve25519.KeyAgreement.PrivateKey {
        Curve25519.KeyAgreement.PrivateKey()
    }

    static func sharedSecret(privateKey: Curve25519.KeyAgreement.PrivateKey,
                             peerPublicKey: Data) throws -> SharedSecret {
        guard peerPublicKey.count == 32 else { throw PairingError.cryptoFailed }
        do {
            let peer = try Curve25519.KeyAgreement.PublicKey(rawRepresentation: peerPublicKey)
            return try privateKey.sharedSecretFromKeyAgreement(with: peer)
        } catch {
            throw PairingError.cryptoFailed
        }
    }

    static func wrapKey(_ shared: SharedSecret, slotID: String) -> SymmetricKey {
        HKDF<SHA256>.deriveKey(inputKeyMaterial: material(shared),
                               salt: Data(slotID.utf8),
                               info: wrapInfo,
                               outputByteCount: 32)
    }

    /// Both devices derive the same six digits. A person compares them out
    /// of band, which is what makes an active relay visible.
    static func sas(_ shared: SharedSecret, slotID: String) -> String {
        let key = HKDF<SHA256>.deriveKey(inputKeyMaterial: material(shared),
                                         salt: Data(slotID.utf8),
                                         info: sasInfo,
                                         outputByteCount: 8)
        return code(from: key)
    }

    static func code(from key: SymmetricKey) -> String {
        let bytes = key.withUnsafeBytes { buffer in
            Array(Data(bytes: buffer.baseAddress!, count: buffer.count).prefix(4))
        }
        let value = bytes.reduce(UInt32(0)) { ($0 << 8) | UInt32($1) } % 1_000_000
        return String(format: "%06d", value)
    }

    /// CryptoKit's HKDF takes a SymmetricKey, while X25519 hands back a
    /// SharedSecret. This is the one conversion between them.
    private static func material(_ shared: SharedSecret) -> SymmetricKey {
        shared.withUnsafeBytes { buffer in
            SymmetricKey(data: Data(bytes: buffer.baseAddress!, count: buffer.count))
        }
    }

    static func seal(spaceID: String, masterKey: Data, using key: SymmetricKey) throws -> Data {
        guard masterKey.count == 32, SyncKeys.isIdentifier(spaceID) else {
            throw PairingError.cryptoFailed
        }
        let payload = PairingPayload(space_id: spaceID,
                                     master_key: PairingBase64URL.encode(masterKey))
        do {
            let plain = try JSONEncoder().encode(payload)
            return try ChaChaPoly.seal(plain, using: key).combined
        } catch {
            throw PairingError.cryptoFailed
        }
    }

    static func open(_ ciphertext: Data, using key: SymmetricKey) throws -> (spaceID: String, masterKey: Data) {
        do {
            let box = try ChaChaPoly.SealedBox(combined: ciphertext)
            let plain = try ChaChaPoly.open(box, using: key)
            let payload = try JSONDecoder().decode(PairingPayload.self, from: plain)
            guard SyncKeys.isIdentifier(payload.space_id),
                  let master = PairingBase64URL.decode(payload.master_key),
                  master.count == 32 else {
                throw PairingError.cryptoFailed
            }
            return (payload.space_id, master)
        } catch let error as PairingError {
            throw error
        } catch {
            throw PairingError.cryptoFailed
        }
    }

    private struct PairingPayload: Codable {
        let space_id: String
        let master_key: String
    }
}

/// The pairing endpoints, as the session sees them. A protocol so a full
/// handoff can be tested without a network.
protocol PairingTransport {
    func createSlot(spaceID: String, token: String, publicKey: Data) async throws -> PairingSlot
    func lookup(code: String) async throws -> PairingLookup
    func join(slotID: String, joinToken: String, publicKey: Data) async throws
    func seal(slotID: String, token: String, ciphertext: Data) async throws
    func slotState(slotID: String, token: String) async throws -> PairingSlotState
    func sealedState(slotID: String, joinToken: String) async throws -> PairingSealedState
    func consume(slotID: String, token: String) async throws
}

/// HTTP client for `/v1/pair/*`. It has its own session, for the same reason
/// `SyncService` does: this traffic leaves the machine.
struct PairingService: PairingTransport {
    let baseURL: URL
    private let session: URLSession

    init(baseURL: URL) throws {
        let scheme = baseURL.scheme?.lowercased() ?? ""
        let host = baseURL.host?.lowercased() ?? ""
        let loopback = host == "127.0.0.1" || host == "localhost" || host == "::1"
        guard scheme == "https" || (scheme == "http" && loopback) else {
            throw PairingError.notConfigured
        }
        self.baseURL = baseURL
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 30
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        self.session = URLSession(configuration: configuration)
    }

    func createSlot(spaceID: String, token: String, publicKey: Data) async throws -> PairingSlot {
        let body: [String: Any] = ["space_id": spaceID,
                                   "pub_a": PairingBase64URL.encode(publicKey)]
        let (data, _) = try await send(path: "v1/pair/slots", method: "POST",
                                       token: token, body: body)
        guard let object = decodeObject(data),
              let slotID = object["slot_id"].string,
              let code = object["code"].string,
              PairingCode.isValid(code),
              let expires = object["expires_at"].double else {
            throw PairingError.invalidResponse
        }
        return PairingSlot(slotID: slotID, code: code,
                           expiresAt: Date(timeIntervalSince1970: expires))
    }

    func lookup(code: String) async throws -> PairingLookup {
        guard PairingCode.isValid(code) else { throw PairingError.invalidCode }
        let (data, _) = try await send(path: "v1/pair/lookup", method: "POST",
                                       token: nil, body: ["code": code])
        guard let object = decodeObject(data),
              let slotID = object["slot_id"].string,
              let spaceID = object["space_id"].string,
              let pubA = object["pub_a"].string,
              let publicKeyA = PairingBase64URL.decode(pubA),
              publicKeyA.count == 32,
              let joinToken = object["join_token"].string,
              let expires = object["expires_at"].double else {
            throw PairingError.invalidResponse
        }
        return PairingLookup(slotID: slotID, spaceID: spaceID, publicKeyA: publicKeyA,
                             joinToken: joinToken,
                             expiresAt: Date(timeIntervalSince1970: expires),
                             attemptsLeft: Int(object["attempts_left"].double ?? 0))
    }

    func join(slotID: String, joinToken: String, publicKey: Data) async throws {
        let body: [String: Any] = ["pub_b": PairingBase64URL.encode(publicKey)]
        _ = try await send(path: "v1/pair/slots/\(slotID)", method: "PUT",
                           token: joinToken, body: body)
    }

    func seal(slotID: String, token: String, ciphertext: Data) async throws {
        let body: [String: Any] = ["ciphertext": PairingBase64URL.encode(ciphertext)]
        _ = try await send(path: "v1/pair/slots/\(slotID)/sealed", method: "PUT",
                           token: token, body: body)
    }

    func slotState(slotID: String, token: String) async throws -> PairingSlotState {
        let (data, _) = try await send(path: "v1/pair/slots/\(slotID)", method: "GET",
                                       token: token, body: nil)
        guard let object = decodeObject(data),
              let ready = object["ready"].bool,
              let expires = object["expires_at"].double else {
            throw PairingError.invalidResponse
        }
        var pubB: Data?
        if let encoded = object["pub_b"].string {
            pubB = PairingBase64URL.decode(encoded)
        }
        var ciphertext: Data?
        if let encoded = object["ciphertext"].string {
            ciphertext = PairingBase64URL.decode(encoded)
        }
        return PairingSlotState(ready: ready, publicKeyB: pubB, ciphertext: ciphertext,
                                expiresAt: Date(timeIntervalSince1970: expires))
    }

    func sealedState(slotID: String, joinToken: String) async throws -> PairingSealedState {
        let (data, _) = try await send(path: "v1/pair/slots/\(slotID)/sealed",
                                       method: "GET", token: joinToken, body: nil)
        guard let object = decodeObject(data),
              let ready = object["ready"].bool,
              let expires = object["expires_at"].double else {
            throw PairingError.invalidResponse
        }
        var ciphertext: Data?
        if let encoded = object["ciphertext"].string {
            ciphertext = PairingBase64URL.decode(encoded)
        }
        return PairingSealedState(ready: ready, spaceID: object["space_id"].string,
                                  ciphertext: ciphertext,
                                  expiresAt: Date(timeIntervalSince1970: expires))
    }

    func consume(slotID: String, token: String) async throws {
        _ = try await send(path: "v1/pair/slots/\(slotID)", method: "DELETE",
                           token: token, body: nil)
    }

    private func url(_ path: String) -> URL {
        baseURL.appendingPathComponent(path)
    }

    private func decodeObject(_ data: Data) -> JSON? {
        try? JSONDecoder().decode(JSON.self, from: data)
    }

    private func send(path: String, method: String, token: String?,
                      body: [String: Any]?) async throws -> (Data, HTTPURLResponse) {
        var request = URLRequest(url: url(path))
        request.httpMethod = method
        if let token {
            request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let data: Data, response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw PairingError.transport("connection_failed")
        }
        guard let http = response as? HTTPURLResponse else { throw PairingError.invalidResponse }
        switch http.statusCode {
        case 200...299:
            return (data, http)
        case 401, 403:
            throw PairingError.unauthorized
        case 404:
            throw PairingError.notFound
        case 410:
            throw PairingError.expired
        default:
            let code = decodeObject(data)?["error"].string ?? "http_\(http.statusCode)"
            throw PairingError.rejected(code)
        }
    }
}

/// The first device: it owns the space, so it owns the master key. It shows
/// the code, waits for the second device's public key, then seals the key.
struct PairingInitiator {
    let transport: any PairingTransport
    let spaceID: String
    let token: String
    let masterKey: Data

    func start() async throws -> PairingInvitation {
        let privateKey = PairingCrypto.newKeyPair()
        let slot = try await transport.createSlot(
            spaceID: spaceID, token: token,
            publicKey: privateKey.publicKey.rawRepresentation)
        return PairingInvitation(slot: slot, spaceID: spaceID,
                                 masterKey: masterKey, privateKey: privateKey)
    }

    /// A single poll. The UI calls this until it returns `.sealed`.
    func poll(_ invitation: PairingInvitation) async throws -> PairingFinish {
        let state = try await transport.slotState(slotID: invitation.slot.slotID,
                                                  token: token)
        guard let publicKeyB = state.publicKeyB else {
            return .waiting(expiresAt: state.expiresAt)
        }
        let shared = try PairingCrypto.sharedSecret(privateKey: invitation.privateKey,
                                                    peerPublicKey: publicKeyB)
        let wrap = PairingCrypto.wrapKey(shared, slotID: invitation.slot.slotID)
        if state.ciphertext == nil {
            let ciphertext = try PairingCrypto.seal(spaceID: invitation.spaceID,
                                                    masterKey: invitation.masterKey,
                                                    using: wrap)
            try await transport.seal(slotID: invitation.slot.slotID, token: token,
                                     ciphertext: ciphertext)
        }
        return .sealed(sas: PairingCrypto.sas(shared, slotID: invitation.slot.slotID))
    }
}

/// The second device: it never sees the master key until the first device
/// seals it to this session's ephemeral public key.
struct PairingJoiner {
    let transport: any PairingTransport
    let code: String
    let privateKey: Curve25519.KeyAgreement.PrivateKey
    let lookup: PairingLookup
    let shared: SharedSecret

    /// Looks the code up and publishes this device's public key. The code
    /// is spent as soon as this succeeds.
    static func begin(transport: any PairingTransport, code: String) async throws -> PairingJoiner {
        guard let normalized = PairingCode.normalize(code) else {
            throw PairingError.invalidCode
        }
        let lookup = try await transport.lookup(code: normalized)
        let privateKey = PairingCrypto.newKeyPair()
        let shared = try PairingCrypto.sharedSecret(privateKey: privateKey,
                                                    peerPublicKey: lookup.publicKeyA)
        try await transport.join(slotID: lookup.slotID, joinToken: lookup.joinToken,
                                 publicKey: privateKey.publicKey.rawRepresentation)
        return PairingJoiner(transport: transport, code: normalized,
                             privateKey: privateKey, lookup: lookup, shared: shared)
    }

    /// A single poll. The UI calls this until it returns `.joined`.
    func poll() async throws -> PairingReceive {
        let state = try await transport.sealedState(slotID: lookup.slotID,
                                                    joinToken: lookup.joinToken)
        guard let ciphertext = state.ciphertext else {
            return .waiting(expiresAt: state.expiresAt)
        }
        let wrap = PairingCrypto.wrapKey(shared, slotID: lookup.slotID)
        let opened = try PairingCrypto.open(ciphertext, using: wrap)
        guard opened.spaceID == lookup.spaceID else { throw PairingError.cryptoFailed }
        return .joined(spaceID: opened.spaceID, masterKey: opened.masterKey,
                       sas: PairingCrypto.sas(shared, slotID: lookup.slotID))
    }
}
