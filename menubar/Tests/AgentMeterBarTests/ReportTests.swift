import XCTest
@testable import AgentMeterBar

final class ReportTests: XCTestCase {
    private func snapshot(_ sources: String) throws -> Snapshot {
        Snapshot(try JSONDecoder().decode(JSON.self, from: Data("{\"sources\":\(sources)}".utf8)))
    }

    func testMixedSourcesConvertToSingleCurrencyAndPreserveReasoning() throws {
        let snap = try snapshot("""
        [{"id":"imported_history","scope":"local_imported_history","metrics":{
           "tokens":{"value":{"periods":{"7d":{"totals":{"total_tokens":100,"output":20,"requests":4},"groups":[{"app":"codex","model":"gpt-5.4","total_tokens":100,"output":20}]}}}},
           "cost":{"value":{"basis":"local_price_table","unit":"USD","periods":{"7d":{"amount":2,"models":{"gpt-5.4":2}}}}}}},
         {"id":"deepseek_harness","scope":"local_session_history","metrics":{
           "tokens":{"value":{"periods":{"7d":{"totals":{"total_tokens":50,"fresh_input":20,"output":10,"reasoning":20},"groups":[{"app":"dsh","model":"deepseek-v4","total_tokens":50,"reasoning":20,"peak":{"total_tokens":30},"offpeak":{"total_tokens":20}}]}}}},
           "cost":{"value":{"basis":"local_price_table","unit":"CNY","periods":{"7d":{"amount":3,"peak_models":{"deepseek-v4":2},"offpeak_models":{"deepseek-v4":1}}}}}}}]
        """)
        let report = try XCTUnwrap(ReportData.build(snapshot: snap, period: .week, now: Date()))
        XCTAssertEqual(report.totalTokens, 150)
        XCTAssertEqual(report.output, 50)
        XCTAssertEqual(report.costAmount, 17.5)
        XCTAssertEqual(report.costUnit, "CNY")
        XCTAssertFalse(report.costText.contains(" + "))
        XCTAssertFalse(report.costText.contains("$"))
        XCTAssertEqual(Fmt.moneyTotal(["USD": 2, "CNY": 3]), 17.5)
        XCTAssertEqual(Fmt.usd(2), Fmt.amount(14.5, unit: "CNY"))
        XCTAssertEqual(report.deepseek.totalTokens, 50)
        XCTAssertEqual(report.deepseek.peakCosts["CNY"], 2)
        XCTAssertEqual(report.deepseek.offpeakCosts["CNY"], 1)
        XCTAssertTrue(report.sourceNote.contains("历史导入"))
    }

    func testSharedImportedModelCostsBelongToEachApp() throws {
        let snap = try snapshot("""
        [{"id":"imported_history","scope":"local_imported_history","metrics":{
          "tokens":{"value":{"periods":{"7d":{"totals":{"total_tokens":15},"groups":[
            {"app":"codex","model":"shared","total_tokens":10},{"app":"claude","model":"shared","total_tokens":5}]}}}},
          "cost":{"value":{"basis":"local_price_table","unit":"CNY","periods":{"7d":{"amount":"3","models":{"shared":"3"},
            "app_models":{"codex":{"shared":"2"},"claude":{"shared":"1"}}}}}}}}]
        """)
        let data = try XCTUnwrap(LocalUsage.merged(snapshot: snap, period: .week))
        XCTAssertEqual(data["groups"].array.map { LocalUsage.groupCost($0, data: data)["CNY"] }, [2, 1])
        XCTAssertEqual(Catalog.applicationID("codex_images"), "codex")
        XCTAssertEqual(Catalog.applicationID("kimi_chat"), "kimi_desktop")
    }

    func testImageOnlyReportAndUnknownCalls() throws {
        let snap = try snapshot("""
        [{"id":"codex","metrics":{"image_generation":{"status":"partial","value":{"currency":"USD","quality_assumption":"high","call_counts_available":false,"periods":{"7d":{"images":8,"calls":0,"estimated_cost":"0.4"}}}}}}]
        """)
        let report = try XCTUnwrap(ReportData.build(snapshot: snap, period: .week, now: Date()))
        XCTAssertEqual(report.imageUsage?.images, 8)
        XCTAssertNil(report.imageUsage?.calls)
        XCTAssertEqual(report.totalTokens, 0)
        XCTAssertFalse(report.hasTokenUsage)
        XCTAssertEqual(report.costText, "—")
        XCTAssertTrue(report.sourceNote.contains("本机记录"))
        XCTAssertTrue(report.imageUsage?.partial == true)
    }

    func testEmptySnapshotHasNoReport() throws {
        XCTAssertNil(ReportData.build(snapshot: try snapshot("[]"), period: .today, now: Date()))
    }

    func testMergedCacheReusesOnlyCurrentSnapshotPeriods() throws {
        let first = try snapshot("[]")
        let second = try snapshot("[]")
        let cache = LocalUsageMergedCache()
        let value: JSON = .object(["totals": .object(["total_tokens": .number(42)])])

        XCTAssertEqual(cache.value(for: first, period: .today) { value }, value)
        XCTAssertEqual(cache.value(for: first, period: .today) { .null }, value)
        XCTAssertEqual(cache.computations, 1)
        XCTAssertEqual(cache.value(for: first, period: .month) { value }, value)
        XCTAssertEqual(cache.computations, 2)
        XCTAssertEqual(cache.value(for: second, period: .today) { .null }, .null)
        XCTAssertEqual(cache.computations, 3)
        XCTAssertEqual(cache.value(for: second, period: .today) { value }, .null)
        XCTAssertEqual(cache.computations, 3, "Empty projections should be cached too")
    }

    func testDateRangeUsesBeijingCalendar() throws {
        let snap = try snapshot("""
        [{"id":"kimi","metrics":{"tokens":{"value":{"periods":{"7d":{"totals":{},"groups":[]}}}}}}]
        """)
        let now = ISO8601DateFormatter().date(from: "2026-10-29T17:00:00Z")!
        let report = try XCTUnwrap(ReportData.build(snapshot: snap, period: .week, now: now))
        XCTAssertEqual(report.dateRange, "2026.10.24 — 2026.10.30")
    }
}
