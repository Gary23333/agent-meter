import XCTest
@testable import AgentMeterBar

/// Pure-logic tests for the Keychain hardening (C2/C3): failure classification,
/// the update-first save decision, and startup slot filtering. Nothing here
/// touches the real Keychain or shows a prompt.
final class KeychainHardeningTests: XCTestCase {

    // MARK: C2 — read failure classification

    func testReadFailureClassification() {
        XCTAssertEqual(SessionReadFailure.from(status: errSecItemNotFound), .notFound)
        XCTAssertEqual(SessionReadFailure.from(status: errSecInteractionNotAllowed),
                       .authorizationRequired(errSecInteractionNotAllowed))
        XCTAssertEqual(SessionReadFailure.from(status: errSecInteractionRequired),
                       .authorizationRequired(errSecInteractionRequired))
        XCTAssertEqual(SessionReadFailure.from(status: errSecAuthFailed),
                       .authorizationRequired(errSecAuthFailed))
        XCTAssertEqual(SessionReadFailure.from(status: errSecParam), .other(errSecParam))
        XCTAssertEqual(SessionReadFailure.from(status: errSecDecode), .other(errSecDecode))
    }

    func testFailureDescriptionsDistinguishReasons() {
        // The three reasons the audit asked to keep apart must read apart.
        let missing = SessionReadFailure.notFound.logDescription
        let locked = SessionReadFailure.authorizationRequired(errSecInteractionNotAllowed).logDescription
        let other = SessionReadFailure.other(errSecParam).logDescription
        XCTAssertNotEqual(missing, locked)
        XCTAssertNotEqual(locked, other)
        XCTAssertTrue(locked.contains("startup"))
    }

    // MARK: C2 — update-first save decision

    func testUpdateFirstSaveDecision() {
        // Existing item: value updated in place, ACL (old grants) untouched.
        XCTAssertEqual(SessionKeychain.updateOutcome(forStatus: errSecSuccess), .updated)
        // Only a genuinely missing item may be added anew.
        XCTAssertEqual(SessionKeychain.updateOutcome(forStatus: errSecItemNotFound), .addNewItem)
        // Any other error must fail the save, not delete-and-recreate.
        XCTAssertEqual(SessionKeychain.updateOutcome(forStatus: errSecAuthFailed), .failed(errSecAuthFailed))
        XCTAssertEqual(SessionKeychain.updateOutcome(forStatus: errSecInteractionNotAllowed),
                       .failed(errSecInteractionNotAllowed))
        XCTAssertEqual(SessionKeychain.updateOutcome(forStatus: errSecParam), .failed(errSecParam))
    }

    // MARK: C3 — startup slot filtering by enabled source

    /// Isolated suite so the user's real preferences are never read or written.
    private var defaults: UserDefaults!
    private var suiteName: String!

    override func setUp() {
        super.setUp()
        suiteName = "AgentMeterBarTests.keychain-hardening." + UUID().uuidString
        defaults = UserDefaults(suiteName: suiteName)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suiteName)
        defaults = nil
        suiteName = nil
        super.tearDown()
    }

    func testStartupSlotsDefaultEnabled() {
        // No persisted toggle: claude defaults to on, like UsageStore's init.
        let slots = ["claude", "claude#2", "qoder", "deepseek_api", "minimax_code#3"]
        XCTAssertEqual(ConnectionManager.startupSlots(slots, defaults: defaults), slots)
    }

    func testStartupSlotsSkipDisabledClaude() {
        defaults.set(false, forKey: "claudeEnabled")
        let slots = ["claude", "qoder", "claude#2", "dreamina#2", "claude#5"]
        XCTAssertEqual(ConnectionManager.startupSlots(slots, defaults: defaults),
                       ["qoder", "dreamina#2"])
    }

    func testStartupSlotsKeepExplicitlyEnabledClaude() {
        defaults.set(true, forKey: "claudeEnabled")
        XCTAssertTrue(ConnectionManager.enabledProviders(defaults: defaults).contains("claude"))
        XCTAssertEqual(ConnectionManager.startupSlots(["claude#2", "qoder"], defaults: defaults),
                       ["claude#2", "qoder"])
    }

    func testStartupSlotsDropUnknownProvidersAndKeepOrder() {
        defaults.set(false, forKey: "claudeEnabled")
        let slots = ["bogus", "zcode#2", "claude", "trae_cn", "bogus#2", "zcode"]
        XCTAssertEqual(ConnectionManager.startupSlots(slots, defaults: defaults),
                       ["zcode#2", "trae_cn", "zcode"])
    }

    func testEnabledProvidersCoverAPIKeySources() {
        let enabled = ConnectionManager.enabledProviders(defaults: defaults)
        for p in WebProvider.apiKeyProviders { XCTAssertTrue(enabled.contains(p.id)) }
        for p in WebProvider.all where p.id != "claude" { XCTAssertTrue(enabled.contains(p.id)) }
    }
}