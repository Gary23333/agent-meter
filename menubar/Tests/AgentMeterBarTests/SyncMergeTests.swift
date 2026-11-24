import XCTest

@testable import AgentMeterBar

final class SyncMergeTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_795_157_000)

    private func snapshot(_ sources: [JSON]) -> Snapshot {
        Snapshot(.object(["schema_version": .number(1), "sources": .array(sources)]))
    }

    private func source(_ id: String, status: String = "available", observed: Double, quota: [JSON] = [], key: String? = nil) -> JSON {
        var object: [String: JSON] = ["id": .string(id), "scope": .string("account"), "status": .string(status),
                                      "observed_at": .object(["epoch_seconds": .number(observed)]),
                                      "metrics": .object(quota.isEmpty ? [:] : ["quota": .object(["status": .string("available"), "value": .array(quota)])])]
        if let key { object["account_key"] = .string(key) }
        return .object(object)
    }

    private func local(_ bucket: String, remaining: Double, minutes: Double = 300) -> JSON {
        .object(["bucket": .string(bucket), "window_minutes": .number(minutes), "remaining_percent": .number(remaining)])
    }

    private func synced(_ account: String, _ bucket: String, remaining: Double, observed: Double, provider: String? = nil,
                        minutes: Double = 300) -> JSON {
        var object: [String: JSON] = ["account": .string(account), "bucket": .string(bucket), "window": .string("\(Int(minutes))m"),
                                      "window_minutes": .number(minutes), "remaining_percent": .number(remaining),
                                      "used_percent": .number(100 - remaining), "observed_at": .number(observed),
                                      "resets_at": .number(observed + 3600), "device": .string(String(repeating: "b", count: 32))]
        if let provider { object["provider"] = .string(provider) }
        return .object(object)
    }

    private func history(quota: [JSON] = [], accounts: [JSON] = []) -> JSON {
        .object(["remote_quota": .array(quota), "accounts": .array(accounts)])
    }

    private func quotas(_ source: Source) -> [JSON] { source.metric("quota")?.value.rows ?? [] }

    func testSameAccountShowsOneBarWithTheNewestValue() {
        let t = now.timeIntervalSince1970
        let base = snapshot([source("kimi", observed: t - 600, quota: [local("limit5h", remaining: 80)])])
        let merged = SyncMerge.merged(base, history: history(quota: [synced("kimi", "limit5h", remaining: 30, observed: t - 60)]), now: now)
        XCTAssertEqual(merged.accountSources.count, 1)
        XCTAssertEqual(quotas(merged.accountSources[0]).count, 1)
        XCTAssertEqual(quotas(merged.accountSources[0])[0]["remaining_percent"].double, 30)
    }

    func testOlderSyncedReadingDoesNotReplaceLocal() {
        let t = now.timeIntervalSince1970
        let base = snapshot([source("kimi", observed: t - 60, quota: [local("limit5h", remaining: 80)])])
        let merged = SyncMerge.merged(base, history: history(quota: [synced("kimi", "limit5h", remaining: 30, observed: t - 600)]), now: now)
        XCTAssertEqual(quotas(merged.accountSources[0])[0]["remaining_percent"].double, 80)
    }

    func testAccountOnlyAnotherDeviceReadsLeavesTheInactiveList() {
        let t = now.timeIntervalSince1970
        let base = snapshot([source("zcode", status: "not_connected", observed: t - 60)])
        XCTAssertEqual(base.inactiveSources.count, 1)
        let merged = SyncMerge.merged(base, history: history(quota: [synced("zcode", "quota", remaining: 55, observed: t - 120)]), now: now)
        XCTAssertTrue(merged.inactiveSources.isEmpty)
        XCTAssertEqual(merged.accountSources.map(\.id), ["zcode"])
        XCTAssertEqual(merged.accountSources[0].status, "available")
    }

    func testNewAccountBecomesAnOrdinaryCardAndAgesToStale() {
        let t = now.timeIntervalSince1970
        let key = String(repeating: "c", count: 24)
        let base = snapshot([source("claude", observed: t, quota: [local("five_hour", remaining: 90)], key: String(repeating: "a", count: 24))])
        let merged = SyncMerge.merged(base, history: history(
            quota: [synced(key, "five_hour", remaining: 10, observed: t - 7200, provider: "claude")]), now: now)
        XCTAssertEqual(merged.accountSources.map(\.id).sorted(), ["claude", "claude#2"])
        let added = merged.accountSources.first { $0.id == "claude#2" }
        XCTAssertEqual(added?.accountKey, key)
        XCTAssertEqual(added?.status, "stale")
    }

    func testAccountFactsFillOnlyWhatTheLocalCardLacks() {
        let t = now.timeIntervalSince1970
        let base = snapshot([source("codex", observed: t, quota: [local("codex", remaining: 50)], key: String(repeating: "a", count: 24))])
        let facts = JSON.object(["account": .string(String(repeating: "a", count: 24)), "provider": .string("codex"),
                                 "observed_at": .number(t - 30), "plan": .string("Pro"),
                                 "reset_cards": .object(["count": .number(2), "expiries": .array([.number(t + 86400)])])])
        let merged = SyncMerge.merged(base, history: history(accounts: [facts]), now: now)
        let card = merged.accountSources[0]
        XCTAssertEqual(card.subscription["plan"].string, "Pro")
        XCTAssertEqual(card.metric("reset_cards")?.value["available_count"].double, 2)
    }

    func testNothingSyncedKeepsTheSnapshot() {
        let base = snapshot([source("kimi", observed: 1, quota: [local("limit5h", remaining: 80)])])
        XCTAssertEqual(SyncMerge.merged(base, history: nil).identity, base.identity)
    }
}
