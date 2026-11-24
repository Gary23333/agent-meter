import XCTest

@testable import AgentMeterBar

/// The expected names are the ones `window_id` in sync_payload.py produces.
final class SyncQuotaWindowTests: XCTestCase {
    func testWindowNamesMatchTheBackend() {
        XCTAssertEqual(AccountsView.syncWindowID(.object(["window": .string("primary"), "window_minutes": .number(10080)])), "primary")
        XCTAssertEqual(AccountsView.syncWindowID(.object(["window": .object(["duration": .number(5), "unit": .string("Hour")])])), "5hour")
        XCTAssertEqual(AccountsView.syncWindowID(.object(["window": .null, "window_minutes": .number(300)])), "300m")
        XCTAssertEqual(AccountsView.syncWindowID(.object(["bucket": .string("credits")])), "all")
    }

    func testLocalRowAndItsSyncedCopyShareAWindow() {
        let local = JSON.object(["bucket": .string("quota"), "window_minutes": .number(10080)])
        let synced = JSON.object(["bucket": .string("quota"), "window": .string("10080m"), "window_minutes": .number(10080)])
        XCTAssertEqual(AccountsView.syncWindowID(local), AccountsView.syncWindowID(synced))
    }
}
