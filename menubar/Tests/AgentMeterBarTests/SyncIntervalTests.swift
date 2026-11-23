import Foundation
import XCTest

@testable import AgentMeterBar

final class SyncIntervalTests: XCTestCase {
    func testIntervalsHaveTheExpectedDurations() {
        XCTAssertNil(SyncInterval.off.seconds)
        XCTAssertEqual(SyncInterval.fiveMinutes.seconds, 300)
        XCTAssertEqual(SyncInterval.thirtyMinutes.seconds, 1_800)
        XCTAssertEqual(SyncInterval.oneHour.seconds, 3_600)
        XCTAssertEqual(SyncInterval.oneDay.seconds, 86_400)
    }

    func testEveryIntervalHasAUniqueLabelAndRawValue() {
        let labels = Set(SyncInterval.allCases.map(\.label))
        let rawValues = Set(SyncInterval.allCases.map(\.rawValue))
        XCTAssertEqual(labels.count, SyncInterval.allCases.count)
        XCTAssertEqual(rawValues.count, SyncInterval.allCases.count)
    }

    func testIntervalPersistsInUserDefaults() throws {
        let suite = "SyncIntervalTests." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }

        SyncInterval.oneHour.store(in: defaults)
        XCTAssertEqual(SyncInterval.stored(in: defaults), .oneHour)

        defaults.set("not-an-interval", forKey: "syncAutoInterval")
        XCTAssertEqual(SyncInterval.stored(in: defaults), .off)
    }
}
