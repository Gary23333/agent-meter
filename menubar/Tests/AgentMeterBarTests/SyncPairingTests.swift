import CryptoKit
import Foundation
import XCTest

@testable import AgentMeterBar

/// In-memory stand-in for `/v1/pair/*`. It keeps the same state transitions
/// as the Python service: a code locates one slot, the joining device writes
/// only its public key, and the first device writes only the sealed bytes.
private final class FakePairingTransport: PairingTransport {
    private struct Slot {
        let spaceID: String
        let spaceToken: String
        let publicKeyA: Data
        var publicKeyB: Data?
        var ciphertext: Data?
        var joinToken: String?
        let expiresAt: Date
        var consumed = false
    }

    private var slots: [String: Slot] = [:]
    private var codes: [String: String] = [:]
    private let expiry = Date().addingTimeInterval(300)
    private(set) var createdSlots: [(spaceID: String, token: String, publicKey: Data)] = []
    private(set) var lookups: [String] = []
    private(set) var joins: [(slotID: String, token: String, publicKey: Data)] = []
    private(set) var seals: [(slotID: String, token: String, ciphertext: Data)] = []

    func createSlot(spaceID: String, token: String, publicKey: Data) async throws -> PairingSlot {
        let slotID = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        var code = String(format: "%06d", Int.random(in: 0..<1_000_000))
        while codes[code] != nil {
            code = String(format: "%06d", Int.random(in: 0..<1_000_000))
        }
        slots[slotID] = Slot(spaceID: spaceID, spaceToken: token, publicKeyA: publicKey,
                             expiresAt: expiry)
        codes[code] = slotID
        createdSlots.append((spaceID, token, publicKey))
        return PairingSlot(slotID: slotID, code: code, expiresAt: expiry)
    }

    func lookup(code: String) async throws -> PairingLookup {
        lookups.append(code)
        guard let slotID = codes[code], let slot = slots[slotID], !slot.consumed else {
            throw PairingError.notFound
        }
        let joinToken = "join-" + slotID
        slots[slotID]?.joinToken = joinToken
        return PairingLookup(slotID: slotID, spaceID: slot.spaceID,
                             publicKeyA: slot.publicKeyA, joinToken: joinToken,
                             expiresAt: slot.expiresAt, attemptsLeft: 4)
    }

    func join(slotID: String, joinToken: String, publicKey: Data) async throws {
        joins.append((slotID, joinToken, publicKey))
        guard var slot = slots[slotID], !slot.consumed else { throw PairingError.notFound }
        guard slot.joinToken == joinToken else { throw PairingError.unauthorized }
        guard slot.publicKeyB == nil else { throw PairingError.rejected("pair_slot_already_paired") }
        slot.publicKeyB = publicKey
        slots[slotID] = slot
    }

    func seal(slotID: String, token: String, ciphertext: Data) async throws {
        seals.append((slotID, token, ciphertext))
        guard var slot = slots[slotID], !slot.consumed else { throw PairingError.notFound }
        guard slot.spaceToken == token else { throw PairingError.unauthorized }
        guard slot.ciphertext == nil else { throw PairingError.rejected("pair_slot_already_sealed") }
        slot.ciphertext = ciphertext
        slots[slotID] = slot
    }

    func slotState(slotID: String, token: String) async throws -> PairingSlotState {
        guard let slot = slots[slotID], !slot.consumed else { throw PairingError.notFound }
        guard slot.spaceToken == token else { throw PairingError.unauthorized }
        return PairingSlotState(ready: slot.publicKeyB != nil,
                                publicKeyB: slot.publicKeyB,
                                ciphertext: slot.ciphertext,
                                expiresAt: slot.expiresAt)
    }

    func sealedState(slotID: String, joinToken: String) async throws -> PairingSealedState {
        guard let slot = slots[slotID], !slot.consumed else { throw PairingError.notFound }
        guard slot.joinToken == joinToken else { throw PairingError.unauthorized }
        return PairingSealedState(ready: slot.ciphertext != nil,
                                  spaceID: slot.spaceID,
                                  ciphertext: slot.ciphertext,
                                  expiresAt: slot.expiresAt)
    }

    func consume(slotID: String, token: String) async throws {
        guard var slot = slots[slotID] else { throw PairingError.notFound }
        guard slot.spaceToken == token else { throw PairingError.unauthorized }
        slot.consumed = true
        slots[slotID] = slot
    }
}

final class PairingCodeTests: XCTestCase {
    func testCodesAreSixAsciiDigits() {
        XCTAssertEqual(PairingCode.normalize("123456"), "123456")
        XCTAssertEqual(PairingCode.normalize("123 456"), "123456")
        XCTAssertEqual(PairingCode.normalize("123-456"), "123456")
        XCTAssertNil(PairingCode.normalize("12345"))
        XCTAssertNil(PairingCode.normalize("1234567"))
        XCTAssertNil(PairingCode.normalize("１２３４５６"))
        XCTAssertNil(PairingCode.normalize("abcdef"))
        XCTAssertEqual(PairingCode.grouped("123456"), "123 456")
        XCTAssertTrue(PairingCode.isValid("123456"))
        XCTAssertFalse(PairingCode.isValid("123 456"))
    }

    func testBase64URLRoundTripsAndHasNoUnsafeCharacters() {
        let data = Data((0..<32).map { _ in UInt8.random(in: 0...255) })
        let encoded = PairingBase64URL.encode(data)
        XCTAssertFalse(encoded.contains("+"))
        XCTAssertFalse(encoded.contains("/"))
        XCTAssertFalse(encoded.contains("="))
        XCTAssertEqual(PairingBase64URL.decode(encoded), data)
        XCTAssertNil(PairingBase64URL.decode("***"))
    }
}

final class PairingCryptoTests: XCTestCase {
    private let slotID = String(repeating: "c", count: 32)
    private let spaceID = String(repeating: "a", count: 32)

    func testBothSidesDeriveTheSameSecurityCode() throws {
        let a = PairingCrypto.newKeyPair()
        let b = PairingCrypto.newKeyPair()
        let sharedA = try PairingCrypto.sharedSecret(
            privateKey: a, peerPublicKey: b.publicKey.rawRepresentation)
        let sharedB = try PairingCrypto.sharedSecret(
            privateKey: b, peerPublicKey: a.publicKey.rawRepresentation)
        XCTAssertEqual(PairingCrypto.sas(sharedA, slotID: slotID),
                       PairingCrypto.sas(sharedB, slotID: slotID))
        XCTAssertEqual(PairingCrypto.sas(sharedA, slotID: slotID).count, 6)
    }

    func testDifferentPeersGiveDifferentCodes() throws {
        let a = PairingCrypto.newKeyPair()
        let b = PairingCrypto.newKeyPair()
        let c = PairingCrypto.newKeyPair()
        let ab = try PairingCrypto.sharedSecret(
            privateKey: a, peerPublicKey: b.publicKey.rawRepresentation)
        let ac = try PairingCrypto.sharedSecret(
            privateKey: a, peerPublicKey: c.publicKey.rawRepresentation)
        XCTAssertNotEqual(PairingCrypto.sas(ab, slotID: slotID),
                          PairingCrypto.sas(ac, slotID: slotID))
    }

    func testTheMasterKeySealsAndOpens() throws {
        let a = PairingCrypto.newKeyPair()
        let b = PairingCrypto.newKeyPair()
        let sharedA = try PairingCrypto.sharedSecret(
            privateKey: a, peerPublicKey: b.publicKey.rawRepresentation)
        let sharedB = try PairingCrypto.sharedSecret(
            privateKey: b, peerPublicKey: a.publicKey.rawRepresentation)
        let master = SyncKeys.randomMasterKey()
        let sealed = try PairingCrypto.seal(spaceID: spaceID, masterKey: master,
                                            using: PairingCrypto.wrapKey(sharedA, slotID: slotID))
        let opened = try PairingCrypto.open(sealed,
                                            using: PairingCrypto.wrapKey(sharedB, slotID: slotID))
        XCTAssertEqual(opened.spaceID, spaceID)
        XCTAssertEqual(opened.masterKey, master)
    }

    func testAStrangerCannotOpenTheSealedKey() throws {
        let a = PairingCrypto.newKeyPair()
        let b = PairingCrypto.newKeyPair()
        let x = PairingCrypto.newKeyPair()
        let sharedAB = try PairingCrypto.sharedSecret(
            privateKey: a, peerPublicKey: b.publicKey.rawRepresentation)
        let sharedAX = try PairingCrypto.sharedSecret(
            privateKey: a, peerPublicKey: x.publicKey.rawRepresentation)
        let sealed = try PairingCrypto.seal(spaceID: spaceID,
                                            masterKey: SyncKeys.randomMasterKey(),
                                            using: PairingCrypto.wrapKey(sharedAB, slotID: slotID))
        XCTAssertThrowsError(try PairingCrypto.open(
            sealed, using: PairingCrypto.wrapKey(sharedAX, slotID: slotID))) { error in
            XCTAssertEqual(error as? PairingError, .cryptoFailed)
        }
    }

    func testAShortPeerKeyIsRefused() {
        let a = PairingCrypto.newKeyPair()
        XCTAssertThrowsError(try PairingCrypto.sharedSecret(
            privateKey: a, peerPublicKey: Data(repeating: 0, count: 31))) { error in
            XCTAssertEqual(error as? PairingError, .cryptoFailed)
        }
    }
}

final class PairingHandoffTests: XCTestCase {
    func testTheFullHandoffGivesBothSidesTheSameKeyAndCode() async throws {
        let transport = FakePairingTransport()
        let spaceID = SyncKeys.randomIdentifier()
        let master = SyncKeys.randomMasterKey()
        let keys = try SyncKeys(masterKey: master, spaceID: spaceID)
        let initiator = PairingInitiator(transport: transport, spaceID: spaceID,
                                         token: keys.authToken, masterKey: master)

        let invitation = try await initiator.start()
        XCTAssertEqual(invitation.slot.code.count, 6)
        XCTAssertEqual(transport.createdSlots.count, 1)
        XCTAssertEqual(transport.createdSlots.first?.publicKey.count, 32)

        // Before the second device joins, the first one is waiting.
        guard case .waiting = try await initiator.poll(invitation) else {
            return XCTFail("the first device should be waiting")
        }

        let joiner = try await PairingJoiner.begin(
            transport: transport, code: PairingCode.grouped(invitation.slot.code))
        XCTAssertEqual(joiner.lookup.spaceID, spaceID)

        // The second device is waiting until the first seals the key.
        guard case .waiting = try await joiner.poll() else {
            return XCTFail("the joining device should be waiting")
        }

        guard case .sealed(let sasA) = try await initiator.poll(invitation) else {
            return XCTFail("the first device should have sealed the key")
        }
        guard case .joined(let joinedSpace, let joinedMaster, let sasB) = try await joiner.poll() else {
            return XCTFail("the joining device should have received the key")
        }

        XCTAssertEqual(joinedSpace, spaceID)
        XCTAssertEqual(joinedMaster, master)
        XCTAssertEqual(sasA, sasB)
        let joinedKeys = try SyncKeys(masterKey: joinedMaster, spaceID: joinedSpace)
        XCTAssertEqual(joinedKeys.authToken, keys.authToken)
        XCTAssertEqual(joinedKeys.authHash, keys.authHash)
    }

    func testAWidgetWithTheWrongCodeIsRefused() async throws {
        let transport = FakePairingTransport()
        let spaceID = SyncKeys.randomIdentifier()
        let master = SyncKeys.randomMasterKey()
        let keys = try SyncKeys(masterKey: master, spaceID: spaceID)
        let initiator = PairingInitiator(transport: transport, spaceID: spaceID,
                                         token: keys.authToken, masterKey: master)
        _ = try await initiator.start()

        XCTAssertNil(PairingCode.normalize("12345"))
        do {
            _ = try await PairingJoiner.begin(transport: transport, code: "000000")
            XCTFail("a code that was never issued must not join")
        } catch {
            XCTAssertEqual(error as? PairingError, .notFound)
        }
    }

    func testANewDeviceCannotReadTheSlotWithItsOwnToken() async throws {
        let transport = FakePairingTransport()
        let spaceID = SyncKeys.randomIdentifier()
        let master = SyncKeys.randomMasterKey()
        let keys = try SyncKeys(masterKey: master, spaceID: spaceID)
        let initiator = PairingInitiator(transport: transport, spaceID: spaceID,
                                         token: keys.authToken, masterKey: master)
        let invitation = try await initiator.start()

        do {
            _ = try await transport.slotState(slotID: invitation.slot.slotID,
                                              token: "not-the-space-token")
            XCTFail("a foreign token must not read the slot")
        } catch {
            XCTAssertEqual(error as? PairingError, .unauthorized)
        }
    }

    func testTheServiceRefusesPlainHttpAwayFromLoopback() {
        XCTAssertThrowsError(try PairingService(baseURL: URL(string: "http://sync.example.com")!)) { error in
            XCTAssertEqual(error as? PairingError, .notConfigured)
        }
        XCTAssertNoThrow(try PairingService(baseURL: URL(string: "http://127.0.0.1:8899")!))
        XCTAssertNoThrow(try PairingService(baseURL: URL(string: "https://sync.example.com")!))
    }
}
