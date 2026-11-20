import CryptoKit
import Foundation
import XCTest

@testable import AgentMeterBar

/// Fixed vectors produced by `agent_meter/sync_crypto.py`. Both clients must
/// derive the same token and key from the same inputs, and either client must
/// open a blob sealed by the other.
final class SyncWindowsVectorTests: XCTestCase {
    private let space = "0123456789abcdef0123456789abcdef"
    private let master = Data((0..<32).map { UInt8($0) })
    private let pythonToken = "TH14GvDazboxTka1eillAGvumzzn4Lw5meO4jUmYlnQ="
    private let pythonHash = "61c14706199816e73b268cd4070c962702d1b6adcad7a505d0cf144725492d77"
    private let pythonEncryptionKey = "4091b4527dd2aee54bb6f36f6850dd86bbdf3f8445d602f309dc1d83bd5d9fb9"
    private let pythonCiphertext = "cMDu5Z5P4Rto9RfKMkURFBORUPr7LpVncv+XAmYZHEQaSe6zjif+4lBj20kA47gQSQdZtA=="

    func testBearerTokenAndHashMatchPython() throws {
        let keys = try SyncKeys(masterKey: master, spaceID: space)
        XCTAssertEqual(keys.authToken, pythonToken)
        XCTAssertEqual(keys.authHash, pythonHash)
    }

    func testEncryptionKeyMatchesPython() throws {
        let keys = try SyncKeys(masterKey: master, spaceID: space)
        XCTAssertEqual(keys.encryptionKey.withUnsafeBytes { Data($0).map { String(format: "%02x", $0) }.joined() },
                       pythonEncryptionKey)
    }

    func testOpensCiphertextSealedByPython() throws {
        let keys = try SyncKeys(masterKey: master, spaceID: space)
        let sealed = try XCTUnwrap(Data(base64Encoded: pythonCiphertext))
        XCTAssertEqual(try keys.open(sealed), Data("agentmeter-python-vector".utf8))
    }
}
