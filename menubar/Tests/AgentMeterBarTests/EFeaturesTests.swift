import XCTest
@testable import AgentMeterBar

final class EFeaturesTests: XCTestCase {
    private func json(_ text: String) -> JSON {
        try! JSONDecoder().decode(JSON.self, from: Data(text.utf8))
    }

    func testClaudeQuotaDisplayRoundsAcrossTheHourAndMidnight() {
        let current = Date(timeIntervalSince1970: 1_794_474_599.785239)
        let weekly = Date(timeIntervalSince1970: 1_794_844_799.785268)

        XCTAssertEqual(Fmt.moment(current, now: current, roundedToMinute: true), "11月12日 17:10")
        XCTAssertEqual(Fmt.moment(weekly, now: current, roundedToMinute: true), "11月17日 00:00")
        XCTAssertEqual(Fmt.moment(weekly, now: current), "11月16日 23:59")
    }

    func testProjectsFeedDecoding() {
        let feed = ProjectsFeed(json("""
        {"projects":[{"project_path":"/a/b","tokens":100,"requests":2,
          "apps":{"codex":{"tokens":100,"requests":2}}},
          {"project_path":"/a/c","tokens":40,"requests":1,
          "apps":{"claude":{"tokens":40,"requests":1}}}],
         "attributed_tokens":140,"total_tokens":200,
         "unattributed":{"tokens":60,"by_app":{"claude":{"tokens":60}}},
         "source_gaps":[{"source":"opencode","reason":"opencode_db_not_found"}]}
        """))
        XCTAssertEqual(feed.items.count, 2)
        XCTAssertEqual(feed.items[0].path, "/a/b")
        XCTAssertEqual(feed.items[0].tokens, 100)
        XCTAssertEqual(feed.items[0].apps.first?.name, "codex")
        XCTAssertEqual(feed.attributed, 140)
        XCTAssertEqual(feed.unattributed, 60)
        XCTAssertEqual(feed.gaps.first?.source, "opencode")
    }

    func testProjectAliases() {
        let encoded = ProjectAliases.encode(["/a/b": "影片项目"])
        let decoded = ProjectAliases.decode(encoded)
        XCTAssertEqual(decoded["/a/b"], "影片项目")
        XCTAssertEqual(ProjectAliases.display("/a/b", aliases: decoded), "影片项目")
        XCTAssertEqual(ProjectAliases.display("/users/x/work/alpha", aliases: [:]), "alpha")
        // Blank aliases are dropped on decode.
        XCTAssertTrue(ProjectAliases.decode(#"{"p":"   "}"#).isEmpty)
        XCTAssertTrue(ProjectAliases.decode("not json").isEmpty)
    }

    func testPeriodReportDecoding() {
        let report = PeriodReport(json("""
        {"current":{"tokens":300,"cost_cny":"1.50","days_with_data":3},
         "previous":{"tokens":200,"cost_cny":"1.00"},
         "delta":{"tokens_pct":50.0,"cost_pct":50.0,"cache_hit_rate_change":0.12},
         "top_movers":[{"model":"glm-5.3-flash","tokens":300,"delta_tokens":100},
                       {"model":"mimo-v2.6-pro","tokens":0,"delta_tokens":-20}],
         "basis":"daily_rollup_base_price_no_peak_split",
         "sources_without_daily_detail":["mystery"]}
        """))
        XCTAssertEqual(report.currentTokens, 300)
        XCTAssertEqual(report.currentCost, 1.5, accuracy: 0.001)
        XCTAssertEqual(report.tokensPct, 50.0)
        XCTAssertEqual(report.movers.count, 2)
        XCTAssertEqual(report.movers[1].delta, -20)
        XCTAssertEqual(report.gaps, ["mystery"])
    }

    func testPeriodReportNullDelta() {
        let report = PeriodReport(json(#"{"current":{"tokens":5},"previous":{"tokens":0},"delta":{"tokens_pct":null}}"#))
        XCTAssertNil(report.tokensPct)
        XCTAssertNil(report.costPct)
    }

    func testStatusFeedDecoding() {
        let feed = StatusFeed(json("""
        {"sources":[{"id":"codex","status":"stale","reason":"rpc_timeout",
                     "observed_at":{"display":"2026-11-09T04:00:00+08:00"},
                     "last_error":"rpc_timeout"}],
         "stale_sources":["codex"],"unpriced_models":["mystery-x"],
         "disabled_sources":["claude"],"low_resource_mode":true,
         "skipped_ledgers":["gemini"],"cache_ttl_seconds":360,
         "snapshot_at":{"display":"2026-11-09T04:00:00+08:00"},"served_from_cache":true}
        """))
        XCTAssertEqual(feed.rows.count, 1)
        XCTAssertEqual(feed.rows[0].status, "stale")
        XCTAssertEqual(feed.stale, ["codex"])
        XCTAssertEqual(feed.unpriced, ["mystery-x"])
        XCTAssertTrue(feed.lowResource)
        XCTAssertEqual(feed.skipped, ["gemini"])
        XCTAssertEqual(feed.ttl, 360)
        XCTAssertTrue(feed.fromCache)
    }
}
