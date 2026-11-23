import CryptoKit
import Foundation
import XCTest

@testable import AgentMeterBar

/// In-memory stand-in for the sync service. Keeps ciphertext only, exactly
/// like the real one, so a test can prove the plaintext never leaves.
private final class FakeTransport: SyncTransport {
    var blobs: [String: Data] = [:]
    var putTokens: [String] = []

    func manifest(spaceID: String, token: String) async throws -> [SyncDeviceManifest] {
        blobs.keys.sorted().map { device in
            SyncDeviceManifest(deviceID: device, size: blobs[device]?.count ?? 0,
                               version: 1, updatedAt: Date(timeIntervalSince1970: 0))
        }
    }

    func put(spaceID: String, deviceID: String, token: String, ciphertext: Data) async throws {
        putTokens.append(token)
        blobs[deviceID] = ciphertext
    }

    func blob(spaceID: String, deviceID: String, token: String) async throws -> Data {
        guard let data = blobs[deviceID] else { throw SyncError.notFound }
        return data
    }

    func delete(spaceID: String, deviceID: String, token: String) async throws {
        blobs[deviceID] = nil
    }
}

/// In-memory stand-in for the loopback backend.
private final class FakeBackend: SyncBackend {
    var payload = Data(#"{"schema":1,"device":"local","usage":[]}"#.utf8)
    var imported: [Data] = []
    var importedLocalDevice: String?
    var askedFor: [String] = []

    func syncPayload(localDevice: String, settings: SyncSettings) async throws -> Data {
        askedFor.append(localDevice)
        return payload
    }

    func importSync(localDevice: String, payload: Data) async throws {
        importedLocalDevice = localDevice
        imported.append(payload)
    }
}

final class SyncKeyTests: XCTestCase {
    private let space = String(repeating: "a", count: 32)
    private let otherSpace = String(repeating: "b", count: 32)

    func testSealAndOpenRoundTrips() throws {
        let keys = try SyncKeys(masterKey: SyncKeys.randomMasterKey(), spaceID: space)
        let plaintext = Data("usage rows, nothing secret".utf8)
        let sealed = try keys.seal(plaintext)
        XCTAssertEqual(try keys.open(sealed), plaintext)
    }

    func testTheCiphertextIsNotThePlaintext() throws {
        let keys = try SyncKeys(masterKey: SyncKeys.randomMasterKey(), spaceID: space)
        let plaintext = Data("usage rows".utf8)
        let sealed = try keys.seal(plaintext)
        XCTAssertNotEqual(sealed, plaintext)
        XCTAssertFalse(String(decoding: sealed, as: UTF8.self).contains("usage rows"))
    }

    func testTheWrongKeyCannotOpen() throws {
        let sealed = try SyncKeys(masterKey: SyncKeys.randomMasterKey(), spaceID: space)
            .seal(Data("payload".utf8))
        let other = try SyncKeys(masterKey: SyncKeys.randomMasterKey(), spaceID: space)
        XCTAssertThrowsError(try other.open(sealed)) { error in
            XCTAssertEqual(error as? SyncError, .cryptoFailed)
        }
    }

    func testAnotherSpaceCannotOpenIt() throws {
        let keys = try SyncKeys(masterKey: SyncKeys.randomMasterKey(), spaceID: space)
        let sealed = try keys.seal(Data("payload".utf8))
        let elsewhere = try SyncKeys(masterKey: keys.masterKey, spaceID: otherSpace)
        XCTAssertThrowsError(try elsewhere.open(sealed))
    }

    func testEachSealUsesAFreshNonce() throws {
        let keys = try SyncKeys(masterKey: SyncKeys.randomMasterKey(), spaceID: space)
        let plaintext = Data("payload".utf8)
        let first = try keys.seal(plaintext)
        let second = try keys.seal(plaintext)
        XCTAssertNotEqual(first, second)
        XCTAssertEqual(try keys.open(first), plaintext)
        XCTAssertEqual(try keys.open(second), plaintext)
    }

    func testTheAuthHashIsTheHashOfTheToken() throws {
        let keys = try SyncKeys(masterKey: SyncKeys.randomMasterKey(), spaceID: space)
        let digest = SHA256.hash(data: Data(keys.authToken.utf8))
            .map { String(format: "%02x", $0) }.joined()
        XCTAssertEqual(keys.authHash, digest)
        XCTAssertEqual(keys.authHash.count, 64)
    }

    func testTheTokenOnlyOpensItsOwnSpace() throws {
        let master = SyncKeys.randomMasterKey()
        let first = try SyncKeys(masterKey: master, spaceID: space)
        let second = try SyncKeys(masterKey: master, spaceID: otherSpace)
        XCTAssertNotEqual(first.authToken, second.authToken)
        XCTAssertNotEqual(first.authHash, second.authHash)
        // The same space with the same key gives the same token.
        let again = try SyncKeys(masterKey: master, spaceID: space)
        XCTAssertEqual(first.authToken, again.authToken)
    }

    func testKeysNeedAProperMasterKeyAndSpace() {
        XCTAssertThrowsError(try SyncKeys(masterKey: Data([1, 2, 3]), spaceID: space))
        XCTAssertThrowsError(try SyncKeys(masterKey: SyncKeys.randomMasterKey(), spaceID: "short"))
    }

    func testIdentifiersAreLowercaseAsciiHex() {
        XCTAssertTrue(SyncKeys.isIdentifier(String(repeating: "0", count: 32)))
        XCTAssertFalse(SyncKeys.isIdentifier(String(repeating: "A", count: 32)))
        XCTAssertFalse(SyncKeys.isIdentifier(String(repeating: "0", count: 31)))
        // Full-width digits look like hex to Character but are not to the
        // service, which only accepts ASCII.
        XCTAssertFalse(SyncKeys.isIdentifier(String(repeating: "０", count: 32)))
        XCTAssertEqual(SyncKeys.randomIdentifier().count, 32)
        XCTAssertTrue(SyncKeys.isIdentifier(SyncKeys.randomIdentifier()))
    }

    func testTheServiceRefusesPlainHttpAwayFromLoopback() {
        XCTAssertThrowsError(try SyncService(baseURL: URL(string: "http://sync.example.com")!))
        XCTAssertNoThrow(try SyncService(baseURL: URL(string: "http://127.0.0.1:8899")!))
        XCTAssertNoThrow(try SyncService(baseURL: URL(string: "https://sync.example.com")!))
    }
}

final class SyncRunnerTests: XCTestCase {
    private let space = String(repeating: "a", count: 32)
    private let local = String(repeating: "1", count: 32)
    private let remote = String(repeating: "2", count: 32)

    func testTheServiceOnlyEverSeesCiphertext() async throws {
        let transport = FakeTransport()
        let keys = try SyncKeys(masterKey: SyncKeys.randomMasterKey(), spaceID: space)
        let runner = SyncRunner(transport: transport, keys: keys, deviceID: local)
        let payload = Data(#"{"usage":[{"date":"2026-11-09"}]}"#.utf8)
        try await runner.upload(payload)
        let stored = try XCTUnwrap(transport.blobs[local])
        XCTAssertNotEqual(stored, payload)
        XCTAssertFalse(String(decoding: stored, as: UTF8.self).contains("2026-11-09"))
        XCTAssertEqual(transport.putTokens, [keys.authToken])
    }

    func testARoundUploadsAndImportsTheOtherDevice() async throws {
        let transport = FakeTransport()
        let keys = try SyncKeys(masterKey: SyncKeys.randomMasterKey(), spaceID: space)
        let backend = FakeBackend()
        let runner = SyncRunner(transport: transport, keys: keys, deviceID: local)
        let coordinator = SyncCoordinator(backend: backend, runner: runner)

        let report = try await coordinator.run()
        XCTAssertTrue(report.uploaded)
        XCTAssertEqual(report.devices, 1)
        // Our own blob must not come back to us as if it were another device.
        XCTAssertEqual(report.importedDevices, [])
        XCTAssertEqual(backend.imported, [])
        XCTAssertEqual(backend.askedFor, [local])

        // A second device with the same key sees the first one's payload.
        let other = FakeTransport()
        other.blobs = transport.blobs
        let otherBackend = FakeBackend()
        let otherRunner = SyncRunner(transport: other, keys: keys, deviceID: remote)
        let otherCoordinator = SyncCoordinator(backend: otherBackend, runner: otherRunner)
        let otherReport = try await otherCoordinator.run()
        XCTAssertEqual(otherReport.importedDevices, [local])
        XCTAssertEqual(otherReport.failedDevices, [])
        XCTAssertEqual(otherBackend.imported.count, 1)
        // The importer says who it is; the payload says whose rows these are.
        XCTAssertEqual(otherBackend.importedLocalDevice, remote)
        XCTAssertEqual(String(decoding: try XCTUnwrap(otherBackend.imported.first), as: UTF8.self),
                       String(decoding: backend.payload, as: UTF8.self))
    }

    func testADeviceWithTheWrongKeyCannotReadTheOtherOne() async throws {
        let transport = FakeTransport()
        let keys = try SyncKeys(masterKey: SyncKeys.randomMasterKey(), spaceID: space)
        let runner = SyncRunner(transport: transport, keys: keys, deviceID: local)
        try await runner.upload(Data("payload".utf8))

        let stranger = try SyncKeys(masterKey: SyncKeys.randomMasterKey(), spaceID: space)
        let otherRunner = SyncRunner(transport: transport, keys: stranger, deviceID: self.remote)
        let devices = try await otherRunner.devices()
        let payloads = try await otherRunner.remotePayloads(from: devices)
        XCTAssertTrue(payloads.isEmpty)
    }

    func testOneUnreadableBlobDoesNotCostTheWholeRound() async throws {
        let transport = FakeTransport()
        let keys = try SyncKeys(masterKey: SyncKeys.randomMasterKey(), spaceID: space)
        let backend = FakeBackend()
        let runner = SyncRunner(transport: transport, keys: keys, deviceID: local)
        try await runner.upload(Data("payload".utf8))

        // A blob that was not written by this key sits next to a good one.
        let good = String(repeating: "3", count: 32)
        transport.blobs[good] = Data("not sealed by us".utf8)
        let otherRunner = SyncRunner(transport: transport, keys: keys, deviceID: self.remote)
        let coordinator = SyncCoordinator(backend: backend, runner: otherRunner)
        let report = try await coordinator.run()
        XCTAssertEqual(report.importedDevices, [local])
        XCTAssertEqual(report.failedDevices, [good])
    }

    func testReportCountsLocalAndRemoteQuotaRows() async throws {
        let transport = FakeTransport()
        let keys = try SyncKeys(masterKey: SyncKeys.randomMasterKey(), spaceID: space)

        // Seed the space with a remote payload carrying two quota rows.
        let remotePayload = Data(#"""
        {"schema":1,"device":"2","usage":[],"quota":[{"account":"a"},{"account":"b"}]}
        """#.utf8)
        let remoteRunner = SyncRunner(transport: transport, keys: keys, deviceID: remote)
        try await remoteRunner.upload(remotePayload)

        // The local payload carries one quota row.
        let localBackend = FakeBackend()
        localBackend.payload = Data(#"""
        {"schema":1,"device":"1","usage":[],"quota":[{"account":"a"}]}
        """#.utf8)
        let localRunner = SyncRunner(transport: transport, keys: keys, deviceID: local)
        let report = try await SyncCoordinator(backend: localBackend, runner: localRunner).run()

        XCTAssertEqual(report.localQuotaRows, 1)
        XCTAssertEqual(report.remoteQuotaRows, 2)
        XCTAssertEqual(report.remoteQuotaDevices, 1)
    }
}

/// The Swift client against the real Python service. The service only ever
/// sees ciphertext, so a passing round proves the two agree on the wire.
final class SyncServiceIntegrationTests: XCTestCase {
    private static let repositoryRoot = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()   // AgentMeterBarTests
        .deletingLastPathComponent()   // Tests
        .deletingLastPathComponent()   // menubar
        .deletingLastPathComponent()   // repository root

    private static func pythonPath() -> String? {
        let candidates = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
        return candidates.first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    func testTheClientAndTheServiceAgreeOnTheWire() async throws {
        guard let python = Self.pythonPath() else {
            throw XCTSkip("no python3 on this machine")
        }
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("agentmeter-sync-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["sync_server/app.py", "--db",
                             directory.appendingPathComponent("sync.db").path, "--port", "0"]
        process.currentDirectoryURL = Self.repositoryRoot
        let output = Pipe()
        let errors = Pipe()
        process.standardOutput = output
        process.standardError = errors
        try process.run()
        defer { process.terminate() }

        let line = try await Self.firstLine(of: output, process: process, errors: errors)
        guard let data = line.data(using: .utf8),
              let object = try? JSONDecoder().decode(JSON.self, from: data),
              let listening = object["listening"].string,
              let url = URL(string: listening) else {
            let detail = String(decoding: errors.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
            XCTFail("the service did not announce its address: \(line) \(detail)")
            return
        }

        let service = try SyncService(baseURL: url)
        let spaceID = SyncKeys.randomIdentifier()
        let keys = try SyncKeys(masterKey: SyncKeys.randomMasterKey(), spaceID: spaceID)
        let deviceID = SyncKeys.randomIdentifier()

        let created = try await service.createSpace(spaceID: spaceID, token: keys.authToken,
                                                    authHash: keys.authHash)
        XCTAssertEqual(created, spaceID)

        let payload = Data(#"{"schema":1,"usage":[{"date":"2026-11-09"}]}"#.utf8)
        let sealed = try keys.seal(payload)
        try await service.put(spaceID: spaceID, deviceID: deviceID,
                              token: keys.authToken, ciphertext: sealed)

        let manifest = try await service.manifest(spaceID: spaceID, token: keys.authToken)
        XCTAssertEqual(manifest.map(\.deviceID), [deviceID])
        XCTAssertEqual(manifest.first?.size, sealed.count)

        let fetched = try await service.blob(spaceID: spaceID, deviceID: deviceID,
                                              token: keys.authToken)
        XCTAssertEqual(fetched, sealed)
        XCTAssertEqual(try keys.open(fetched), payload)

        // The wrong token must not read the space.
        do {
            _ = try await service.manifest(spaceID: spaceID, token: "not-the-token")
            XCTFail("a foreign token must not read the space")
        } catch {
            XCTAssertEqual(error as? SyncError, .unauthorized)
        }

        try await service.delete(spaceID: spaceID, deviceID: deviceID, token: keys.authToken)
        let emptied = try await service.manifest(spaceID: spaceID, token: keys.authToken)
        XCTAssertEqual(emptied, [])
    }

    /// The two-device handoff against the real Python service. This proves
    /// the Swift client and the service agree on every `/v1/pair/*` step.
    func testTheTwoDeviceHandoffAgainstTheRealService() async throws {
        guard let python = Self.pythonPath() else {
            throw XCTSkip("no python3 on this machine")
        }
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("agentmeter-pair-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["sync_server/app.py", "--db",
                             directory.appendingPathComponent("sync.db").path, "--port", "0"]
        process.currentDirectoryURL = Self.repositoryRoot
        let output = Pipe()
        let errors = Pipe()
        process.standardOutput = output
        process.standardError = errors
        try process.run()
        defer { process.terminate() }

        let line = try await Self.firstLine(of: output, process: process, errors: errors)
        guard let data = line.data(using: .utf8),
              let object = try? JSONDecoder().decode(JSON.self, from: data),
              let listening = object["listening"].string,
              let url = URL(string: listening) else {
            XCTFail("the service did not announce its address: \(line)")
            return
        }

        let spaceID = SyncKeys.randomIdentifier()
        let master = SyncKeys.randomMasterKey()
        let keys = try SyncKeys(masterKey: master, spaceID: spaceID)
        let sync = try SyncService(baseURL: url)
        _ = try await sync.createSpace(spaceID: spaceID, token: keys.authToken,
                                       authHash: keys.authHash)
        let pairing = try PairingService(baseURL: url)

        let initiator = PairingInitiator(transport: pairing, spaceID: spaceID,
                                         token: keys.authToken, masterKey: master)
        let invitation = try await initiator.start()
        XCTAssertEqual(invitation.slot.code.count, 6)

        let joiner = try await PairingJoiner.begin(
            transport: pairing, code: PairingCode.grouped(invitation.slot.code))
        XCTAssertEqual(joiner.lookup.spaceID, spaceID)

        guard case .sealed(let sasA) = try await initiator.poll(invitation) else {
            return XCTFail("the first device did not seal the key")
        }
        guard case .joined(let joinedSpace, let joinedMaster, let sasB) = try await joiner.poll() else {
            return XCTFail("the joining device did not receive the key")
        }
        XCTAssertEqual(joinedSpace, spaceID)
        XCTAssertEqual(joinedMaster, master)
        XCTAssertEqual(sasA, sasB)

        try await pairing.consume(slotID: invitation.slot.slotID, token: keys.authToken)
        do {
            _ = try await pairing.sealedState(slotID: invitation.slot.slotID,
                                              joinToken: joiner.lookup.joinToken)
            XCTFail("a consumed slot must not answer")
        } catch {
            XCTAssertEqual(error as? PairingError, .expired)
        }
    }

    /// The service announces its address on the first line of stdout.
    private static func firstLine(of pipe: Pipe, process: Process, errors: Pipe) async throws -> String {
        var buffer = Data()
        let deadline = Date().addingTimeInterval(15)
        while !String(decoding: buffer, as: UTF8.self).contains("\n") {
            if Date() > deadline || !process.isRunning {
                // The service died or never spoke up; do not wait for it.
                let detail = String(decoding: errors.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
                XCTFail("the service did not start: \(detail)")
                return ""
            }
            let chunk = pipe.fileHandleForReading.availableData
            if chunk.isEmpty {
                try await Task.sleep(nanoseconds: 20_000_000)
                continue
            }
            buffer.append(chunk)
        }
        return String(decoding: buffer, as: UTF8.self)
            .split(separator: "\n").first.map(String.init) ?? ""
    }
}
