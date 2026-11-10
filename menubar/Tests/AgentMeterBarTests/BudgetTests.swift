import XCTest
@testable import AgentMeterBar

/// Pure-logic tests for the budget payload: parsing, alert copy, event dedup
/// and money formatting. No backend, no notification center.
final class BudgetTests: XCTestCase {
    private func status(_ string: String) throws -> BudgetStatus {
        BudgetStatus(try JSONDecoder().decode(JSON.self, from: Data(string.utf8)))
    }

    private let exceeded = """
    {"status":"ok","schema":1,
     "config":{"schema":1,"daily_cny":"10","weekly_cny":null,"anomaly_multiplier":"2.0"},
     "date":"2026-11-08","week_start":"2026-11-02",
     "daily":{"budget_cny":"10.000000","spent_cny":"12.500000","remaining_cny":"-2.500000",
              "exceeded":true,"partial":false,"unknown_sources":[],
              "top_apps":[{"name":"zcode","amount_cny":"12.500000"}],
              "top_models":[{"name":"glm-5.3","amount_cny":"12.500000"}]},
     "weekly":{"budget_cny":null,"spent_cny":"12.500000","exceeded":false},
     "anomaly":{"triggered":true,"multiplier":"2.000000"},
     "events":[
       {"id":"budget_daily_exceeded:2026-11-08","kind":"daily_exceeded","date":"2026-11-08",
        "budget_cny":"10.000000","spent_cny":"12.500000","excess_cny":"2.500000",
        "top_apps":[{"name":"zcode","amount_cny":"12.500000"}],
        "top_models":[{"name":"account:vendor/GLM-5.3","amount_cny":"12.500000"}]},
       {"id":"budget_anomaly:2026-11-08","kind":"anomaly","date":"2026-11-08",
        "spent_cny":"12.500000","rate_cny_per_hour":"1.041667","baseline_daily_cny":"2.000000",
        "multiplier":"2.000000",
        "top_apps":[{"name":"zcode","amount_cny":"12.500000"}],"top_models":[]}]}
    """

    func testParsesDecimalStringsAndConfig() throws {
        let s = try status(exceeded)
        XCTAssertTrue(s.isOK)
        XCTAssertEqual(s.dailyBudget, 10)
        XCTAssertEqual(s.dailySpent, 12.5)
        XCTAssertTrue(s.dailyExceeded)
        XCTAssertNil(s.weeklyBudget)
        XCTAssertEqual(s.configDaily, "10")
        XCTAssertEqual(s.configWeekly, "")
        XCTAssertEqual(s.configMultiplier, "2.0")
        XCTAssertTrue(s.showsProgress)
    }

    func testUnsetBudgetHidesProgressAndNeverAlerts() throws {
        let s = try status("""
        {"status":"ok","config":{"daily_cny":null,"weekly_cny":null,"anomaly_multiplier":"2.0"},
         "daily":{"budget_cny":null,"spent_cny":"999","exceeded":false},"events":[]}
        """)
        XCTAssertFalse(s.showsProgress)
        XCTAssertNil(s.dailyBudget)
        XCTAssertEqual(s.alerts, [])
    }

    func testUnknownSpentIsNilNotZero() throws {
        let s = try status("""
        {"status":"ok","config":{"daily_cny":"10"},
         "daily":{"budget_cny":"10.000000","spent_cny":null,"exceeded":true},"events":[]}
        """)
        XCTAssertNil(s.dailySpent)
        XCTAssertTrue(s.showsProgress)   // budget set: row shows "— / ¥10.00"
    }

    func testNotCollectedProducesNoAlerts() throws {
        let s = try status(#"{"status":"not_collected","config":{"daily_cny":null}}"#)
        XCTAssertFalse(s.isOK)
        XCTAssertFalse(s.showsProgress)
        XCTAssertEqual(s.alerts, [])
    }

    func testAlertCopyContainsAmountsAppsAndEstimateNote() throws {
        let alerts = try status(exceeded).alerts
        XCTAssertEqual(alerts.count, 2)
        let daily = try XCTUnwrap(alerts.first)
        XCTAssertEqual(daily.key, "budget|budget_daily_exceeded:2026-11-08")
        XCTAssertEqual(daily.title, "今日估算费用已超日预算")
        XCTAssertTrue(daily.body.contains(Fmt.amount(12.5, unit: "CNY")))
        XCTAssertTrue(daily.body.contains(Fmt.amount(2.5, unit: "CNY")))
        XCTAssertTrue(daily.body.contains("ZCode"))
        XCTAssertTrue(daily.body.contains("GLM-5.3"))
        XCTAssertTrue(daily.body.contains("非实际扣费"))
        let anomaly = alerts[1]
        XCTAssertEqual(anomaly.key, "budget|budget_anomaly:2026-11-08")
        XCTAssertTrue(anomaly.body.contains("倍"))
        XCTAssertTrue(anomaly.body.contains("2 倍"))
    }

    func testEventDedupUsesStableIdsAcrossRecovery() throws {
        let s = try status(exceeded)
        let pending = s.pendingAlerts(fired: [:])
        XCTAssertEqual(pending.count, 2)
        // Simulate the Notifier having fired both; a later poll (even after a
        // collection recovery re-reports the same day) yields nothing new.
        var fired: [String: Double] = [:]
        for alert in pending { fired[alert.key] = 1_794_110_400 }
        XCTAssertEqual(s.pendingAlerts(fired: fired), [])
        // A new day's event id is a new key and does notify.
        let next = try status(exceeded.replacingOccurrences(of: "2026-11-08", with: "2026-11-09"))
        XCTAssertEqual(next.pendingAlerts(fired: fired).count, 2)
    }

    func testWeeklyExceededAlert() throws {
        let s = try status("""
        {"status":"ok","events":[
          {"id":"budget_weekly_exceeded:2026-11-02","kind":"weekly_exceeded","date":"2026-11-02",
           "budget_cny":"60.000000","spent_cny":"62.000000","excess_cny":"2.000000",
           "top_apps":[],"top_models":[]}]}
        """)
        let alert = try XCTUnwrap(s.alerts.first)
        XCTAssertEqual(alert.key, "budget|budget_weekly_exceeded:2026-11-02")
        XCTAssertEqual(alert.title, "本周估算费用已超周预算")
        XCTAssertTrue(alert.body.contains(Fmt.amount(62, unit: "CNY")))
    }

    func testUnknownEventKindIsIgnored() throws {
        let s = try status("""
        {"status":"ok","events":[{"id":"budget_future:2026-11-08","kind":"future_kind"}]}
        """)
        XCTAssertEqual(s.alerts, [])
    }

    func testMoneyFormattingMatchesUsageTab() {
        XCTAssertEqual(Fmt.amount(12.5, unit: "CNY"), "¥12.5")
        XCTAssertEqual(Fmt.amount(14.5, unit: "USD"), Fmt.amount(105.125, unit: "CNY"))
    }
}