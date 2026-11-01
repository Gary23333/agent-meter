import XCTest
@testable import AgentMeterBar

/// Decoding and pure-logic tests for the 会话活动 feed (schema_version 1).
final class ActivityTests: XCTestCase {
    private func row(_ overrides: [String: JSON] = [:]) -> JSON {
        var base: [String: JSON] = [
            "app": .string("zcode"), "granularity": .string("turn"),
            "status": .string("running"), "status_basis": .string("recency"),
            "project_alias": .string("项目A"), "project_path": .string("/Users/u/项目A"),
            "session_id": .string("sess_1"), "subagent": .bool(false),
            "started_at": .object(["epoch_seconds": .number(1000)]),
            "last_event_at": .object(["epoch_seconds": .number(2000)]),
            "last_model": .string("p/GLM-5.3"),
            "requests": .number(3),
            "tokens": .object(["fresh_input": .number(100), "output": .number(20),
                               "reasoning": .number(5), "cache_read": .number(300),
                               "cache_write": .number(10), "total_tokens": .number(435)]),
            "estimated_cost_usd": .number(0.0012), "notes": .string("turn_status_not_session_status"),
            "turn_statuses": .object(["completed": .number(2)]),
            "last_turn_status": .string("completed"), "turns": .number(2),
            "recent_turns": .array([
                .object(["turn": .string("t1"), "status": .string("completed"),
                         "tokens": .number(210), "steps": .number(3)]),
            ]),
        ]
        for (key, value) in overrides { base[key] = value }
        return .object(base)
    }

    private func feed(_ activities: [JSON], meta: [String: JSON] = [:]) -> JSON {
        .object([
            "schema_version": .number(1),
            "generated_at": .object(["epoch_seconds": .number(5000)]),
            "window_hours": .number(24), "idle_after_minutes": .number(15),
            "activities": .array(activities),
            "sources_meta": .object(meta),
        ])
    }

    func testDecodesRowContract() {
        let row = ActivityRow(row())
        XCTAssertEqual(row.app, "zcode")
        XCTAssertEqual(row.granularity, .turn)
        XCTAssertEqual(row.granularity.label, "回合")
        XCTAssertEqual(row.status, .running)
        XCTAssertEqual(row.status.label, "进行中")
        XCTAssertEqual(row.projectAlias, "项目A")
        XCTAssertEqual(row.requests, 3)
        XCTAssertEqual(row.tokens?.total, 435)
        XCTAssertEqual(row.estimatedCostUSD ?? 0, 0.0012, accuracy: 1e-9)
        XCTAssertEqual(row.lastTurnStatus, .completed)
        XCTAssertEqual(row.turns, 2)
        XCTAssertEqual(row.recentTurns.count, 1)
        XCTAssertEqual(row.recentTurns.first?.steps, 3)
        XCTAssertTrue(row.hasTurnDetail)
    }

    func testUnknownFieldsAndValuesDegradeHonestly() {
        // 未知状态绝不解读为失败。
        let json = row(["status": .string("something_new"), "granularity": .string("later_kind"),
                        "tokens": .null, "last_turn_status": .null,
                        "turn_statuses": .object(["weird": .number(1)])])
        let parsed = ActivityRow(json)
        XCTAssertEqual(parsed.status, .unknown)
        XCTAssertEqual(parsed.granularity, .recentActivity)
        XCTAssertNil(parsed.tokens)
        XCTAssertNil(parsed.lastTurnStatus)
        // Unrecognized turn status keys are preserved verbatim, never mapped.
        XCTAssertEqual(parsed.turnStatuses, ["weird": 1])
    }

    func testAliasOverrideWinsOverBackendAlias() {
        let aliases = ["/Users/u/项目A": "我的项目"]
        let parsed = ActivityRow(row())
        XCTAssertEqual(parsed.displayName(aliases: aliases), "我的项目")
        XCTAssertEqual(parsed.displayName(aliases: [:]), "项目A")
        let unowned = ActivityRow(row(["project_path": .null, "project_alias": .null]))
        XCTAssertEqual(unowned.displayName(aliases: aliases), "未归属")
    }

    func testSortingRunningFirstThenRecency() {
        let running = ActivityRow(row(["session_id": .string("r"),
                                       "last_event_at": .object(["epoch_seconds": .number(100)])]))
        let ended = ActivityRow(row(["status": .string("suspected_ended"), "session_id": .string("s"),
                                     "last_event_at": .object(["epoch_seconds": .number(9000)])]))
        let failed = ActivityRow(row(["status": .string("failed"), "session_id": .string("f"),
                                      "last_event_at": .object(["epoch_seconds": .number(9500)])]))
        let sorted = ActivityFeed.sorted([failed, ended, running])
        XCTAssertEqual(sorted.map(\.sessionID), ["r", "s", "f"])
    }

    func testFilterChips() {
        let running = ActivityRow(row(["session_id": .string("r")]))
        let done = ActivityRow(row(["status": .string("completed"), "session_id": .string("c")]))
        XCTAssertTrue(ActivityFeed.Filter.running.matches(running))
        XCTAssertFalse(ActivityFeed.Filter.running.matches(done))
        XCTAssertTrue(ActivityFeed.Filter.rest.matches(done))
        XCTAssertTrue(ActivityFeed.Filter.all.matches(done))
    }

    func testFeedMetaAndRunningCount() {
        let parsed = ActivityFeed(feed([row(), row(["status": .string("completed")])],
                                      meta: ["zcode": .object(["status": .string("available"), "activities": .number(2)]),
                                             "dsh": .object(["status": .string("not_connected"), "reason": .string("dsh_sessions_not_found"), "activities": .number(0)])]))
        XCTAssertEqual(parsed.windowHours, 24)
        XCTAssertEqual(parsed.runningCount, 1)
        XCTAssertTrue(parsed.hasRunning)
        XCTAssertEqual(parsed.sourcesMeta["dsh"]?.reason, "dsh_sessions_not_found")
        XCTAssertEqual(parsed.sourcesMeta["zcode"]?.activities, 2)
    }

    func testCadenceSelection() {
        XCTAssertEqual(ActivityCadence.interval(panelVisible: true, hasRunning: false), 5)
        XCTAssertEqual(ActivityCadence.interval(panelVisible: false, hasRunning: true), 15)
        XCTAssertEqual(ActivityCadence.interval(panelVisible: false, hasRunning: false), 120)
        // Watching the panel always uses the fast lane, even when idle.
        XCTAssertEqual(ActivityCadence.interval(panelVisible: true, hasRunning: true), 5)
    }

    func testGranularityCaveatsCoverEveryKind() {
        for kind in [ActivityGranularity.imageCall, .turn, .steps, .turnSteps, .recentActivity] {
            XCTAssertFalse(kind.caveat.isEmpty)
            XCTAssertFalse(kind.label.isEmpty)
        }
    }

    func testCodexImageRowDecodesCallCounts() {
        let parsed = ActivityRow(row(["app": .string("codex_images"),
                                      "granularity": .string("image_call"),
                                      "status": .string("failed"),
                                      "status_basis": .string("explicit_event"),
                                      "project_path": .null, "project_alias": .null,
                                      "tokens": .null, "calls": .number(4),
                                      "failed_calls": .number(1), "generating_calls": .number(0)]))
        XCTAssertEqual(parsed.appLabel, "Codex 生图")
        XCTAssertEqual(parsed.status, .failed)
        XCTAssertEqual(parsed.calls, 4)
        XCTAssertEqual(parsed.failedCalls, 1)
        XCTAssertNil(parsed.tokens)
        XCTAssertEqual(parsed.displayName(aliases: [:]), "未归属")
    }
}
