import XCTest
@testable import AgentMeterBar

/// The 桌宠 tab: its catalogue of states, the words made from a frame, the shared feed, the stage's rules and the
/// pieces of the page address. Nothing here needs a backend or a window.
final class PetCatalogTests: XCTestCase {
    func testStatesAndReactionsAreCompleteAndDistinct() {
        let states = PetCatalog.states.map(\.id)
        XCTAssertEqual(Set(states).count, states.count)
        // The canonical states of the backend brain (agent_meter/pet.py STATES): none missing, none invented.
        XCTAssertEqual(Set(states), ["offline", "exhausted", "alarm", "waiting", "busy", "working", "painting", "tired",
                                      "alert", "focus", "excited", "confused", "sleeping", "idle"])
        XCTAssertEqual(PetCatalog.reactions.map(\.id), ["celebrate", "eating", "startle", "wave", "painting"])
        for info in PetCatalog.states + PetCatalog.reactions {
            XCTAssertFalse(info.label.isEmpty, info.id)
            XCTAssertFalse(info.symbol.isEmpty, info.id)
            XCTAssertGreaterThan(info.trigger.count, 6, info.id)
        }
    }

    func testLookupFallsBackToTheIdItself() {
        XCTAssertEqual(PetCatalog.label("working"), "干活中")
        XCTAssertEqual(PetCatalog.label("celebrate"), "庆祝")
        XCTAssertEqual(PetCatalog.label("nonsense"), "nonsense")
        XCTAssertNil(PetCatalog.info("nonsense"))
    }

    func testEveryPanelTabCanBeTheTargetOfAPetAction() {
        XCTAssertEqual(PetAction.tabs, Set(Tab.allCases.map(\.rawValue)))
        XCTAssertEqual(Tab(rawValue: "pet"), .pet)
        XCTAssertEqual(Tab.pet.label, "桌宠")
    }
}

@MainActor
final class PetStatusTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_800_000_000)

    private func status(_ state: String) throws -> PetStatus {
        try XCTUnwrap(PetStatus.parse(PetController.demoFrame(state: state, now: now)))
    }

    func testAFrameBecomesWordsAndNumbers() throws {
        let s = try status("working")
        XCTAssertEqual(s.state, "working")
        XCTAssertEqual(s.stateLabel, "干活中")
        XCTAssertEqual(s.energy.remaining, 82)
        XCTAssertTrue(s.energy.known)
        XCTAssertEqual(s.meters.map(\.source), ["codex", "claude"])
        XCTAssertEqual(s.running, 1)
        XCTAssertEqual(s.sessions.first?.label, "Codex")
        XCTAssertEqual(s.summaryLine(now: now), "Codex · 5 小时 还剩 82% · 2时31分 · 1 个会话进行中")
    }

    func testUnknownIsNeverShownAsZero() throws {
        let offline = try XCTUnwrap(PetStatus.parse(PetController.offlineFrame(now: now)))
        XCTAssertEqual(offline.state, "offline")
        XCTAssertFalse(offline.energy.known)
        XCTAssertNil(offline.energy.remaining)
        XCTAssertEqual(offline.summaryLine(now: now), "还没读到百分比额度")
        var stale = offline
        stale.energy.stale = true
        XCTAssertEqual(stale.summaryLine(now: now), "额度数据已过期，我也不确定")
        // "known" without a number is not known.
        let odd = try XCTUnwrap(PetStatus.parse(["state": "idle", "energy": ["known": true, "tone": "ok"]]))
        XCTAssertFalse(odd.energy.known)
    }

    func testGarbageIsIgnoredPiecewise() throws {
        XCTAssertNil(PetStatus.parse([:]))
        XCTAssertNil(PetStatus.parse(["mood": "happy"]))
        let s = try XCTUnwrap(PetStatus.parse([
            "state": "busy", "meters": [["id": "a", "remaining": true], ["id": "b", "remaining": 40, "source": "kimi", "name": "Kimi", "window": "5 小时"], ["remaining": 3]],
            "activity": ["running": "many", "apps": [["label": "no app id"], ["app": "codex", "count": 2]]],
            "events": [["id": "x", "kind": "agent_done", "at": "yesterday"], ["id": "y", "kind": "agent_failed", "source": "claude", "at": 5.0]],
            "today": ["known": false, "tokens": 9], "focus": ["active": true, "ends_at": 100.0],
        ]))
        XCTAssertEqual(s.meters.map(\.id), ["b"])                      // a boolean is not a number; a meter needs an id
        XCTAssertEqual(s.running, 0)
        XCTAssertEqual(s.sessions.map(\.app), ["codex"])
        XCTAssertEqual(s.events.map(\.id), ["y"])
        XCTAssertNil(s.todayTokens)                                     // known: false wins over a number
        XCTAssertEqual(s.focusEndsAt, Date(timeIntervalSince1970: 100))
    }

    func testRemindersKeepOnlyRealPanelTargets() throws {
        let s = try XCTUnwrap(PetStatus.parse(["state": "alert", "reminders": [
            ["id": "a", "text": "Codex 重置卡即将到期", "tone": "warn", "action": ["kind": "open_panel", "tab": "accounts"]],
            ["id": "b", "title": "只有标题", "action": ["kind": "run_script", "tab": "accounts"]],
            ["id": "c", "text": ""], ["text": "no id"],
        ]]))
        XCTAssertEqual(s.reminders.map(\.id), ["a", "b"])
        XCTAssertEqual(s.reminders[0].tab, "accounts")
        XCTAssertNil(s.reminders[1].tab)                                // only open_panel names a tab
        XCTAssertEqual(s.reminders[1].text, "只有标题")
        XCTAssertEqual(s.reminderCount, 2)
    }

    func testReasonsAreExplainedAndUnknownOnesShownAsTheyAre() {
        XCTAssertNil(PetStatus.gloss("state=working"))
        XCTAssertNil(PetStatus.gloss("preview"))
        XCTAssertEqual(PetStatus.gloss("activity.running=2"), "2 个会话在运行")
        XCTAssertEqual(PetStatus.gloss("energy=low(15)"), "额度偏低（15%）")
        XCTAssertEqual(PetStatus.gloss("energy=ok(82)"), "额度充足（82%）")
        XCTAssertEqual(PetStatus.gloss("waiting=claude"), "Claude 在等你")
        XCTAssertEqual(PetStatus.gloss("idle>=30m"), "已经 30 分钟没有活动")
        XCTAssertEqual(PetStatus.gloss("quota=stale"), "额度数据已过期")
        XCTAssertEqual(PetStatus.gloss("something.new=1"), "something.new=1")
    }

    func testHookEventsReadAsSentences() throws {
        let at = Date(timeIntervalSince1970: 10)
        func text(_ kind: String, _ source: String?) -> String { PetTabView.eventText(.init(id: "e", kind: kind, source: source, text: nil, at: at)) }
        XCTAssertEqual(text("agent_started", "codex"), "Codex 开始了")
        XCTAssertEqual(text("agent_done", "claude"), "Claude Code 完成了")
        XCTAssertEqual(text("agent_waiting", nil), "Agent 在等你")
        XCTAssertEqual(text("agent_failed", "mytool"), "mytool 出错了")
    }
}

@MainActor
final class PetFeedTests: XCTestCase {
    func testItOnlyPollsWhileSomebodyListensAndReplaysTheLatestFrame() {
        let feed = PetFeed()
        XCTAssertFalse(feed.isPolling)
        feed.inject(PetController.demoFrame(state: "alarm"))
        XCTAssertEqual(feed.status?.state, "alarm")

        var seen: [String] = []
        feed.subscribe("a") { seen.append($0["state"] as? String ?? "?") }
        XCTAssertEqual(seen, ["alarm"], "a new listener gets the latest frame at once")
        XCTAssertTrue(feed.isPolling)

        var replaced: [String] = []
        feed.subscribe("a") { replaced.append($0["state"] as? String ?? "?") }
        XCTAssertEqual(replaced, [], "same id: the callbacks are replaced and nothing is replayed")
        XCTAssertEqual(feed.subscriberCount, 1)

        var other: [String] = []
        feed.subscribe("b") { other.append($0["state"] as? String ?? "?") }
        feed.inject(PetController.demoFrame(state: "idle"))
        XCTAssertEqual(other, ["alarm", "idle"])
        XCTAssertEqual(replaced, ["idle"])
        XCTAssertEqual(seen, ["alarm"], "the replaced callback hears nothing more")
        XCTAssertEqual(feed.status?.state, "idle")

        feed.unsubscribe("a")
        XCTAssertTrue(feed.isPolling, "still one listener")
        feed.unsubscribe("b")
        XCTAssertFalse(feed.isPolling)
        XCTAssertEqual(feed.subscriberCount, 0)
    }

    func testOfflineFramesParseLikeAnyOther() {
        let feed = PetFeed()
        feed.inject(PetController.offlineFrame())
        XCTAssertEqual(feed.status?.state, "offline")
        XCTAssertNotNil(feed.updatedAt)
    }
}

@MainActor
final class PetStageTests: XCTestCase {
    func testTheStageNeverGetsRemindersButKeepsEverythingElse() {
        let frame = PetController.demoFrame(state: "alert")
        XCTAssertEqual((frame["reminders"] as? [Any])?.count, 1)
        let stage = PetStageHost.stageFrame(frame)
        XCTAssertEqual((stage["reminders"] as? [Any])?.count, 0)
        XCTAssertEqual(stage["state"] as? String, "alert")
        XCTAssertEqual((stage["energy"] as? [String: Any])?["tone"] as? String, frame["energy"].flatMap { ($0 as? [String: Any])?["tone"] as? String })
        XCTAssertEqual(Set(stage.keys), Set(frame.keys))
    }

    func testPageAddressesCarryTheirMode() throws {
        func items(_ url: URL?) throws -> [String: String] {
            let components = try XCTUnwrap(URLComponents(url: try XCTUnwrap(url), resolvingAgainstBaseURL: false))
            XCTAssertEqual(components.scheme, "agentpet")
            XCTAssertEqual(components.host, "app")
            XCTAssertEqual(components.path, "/runtime/index.html")
            return Dictionary(uniqueKeysWithValues: (components.queryItems ?? []).map { ($0.name, $0.value ?? "") })
        }
        let window = try items(PetPage.url(pack: "gauge", theme: "aurora", scheme: "dark", scale: 1.3, hud: "full", reduceMotion: true, calm: true))
        XCTAssertEqual(window["pack"], "gauge")
        XCTAssertEqual(window["packRoot"], "agentpet://app/pack/")
        XCTAssertEqual(window["theme"], "aurora")
        XCTAssertEqual(window["scheme"], "dark")
        XCTAssertEqual(window["scale"], "1.3")
        XCTAssertEqual(window["hud"], "full")
        XCTAssertEqual(window["reduceMotion"], "1")
        XCTAssertEqual(window["calm"], "1")
        XCTAssertNil(window["embed"])
        XCTAssertNil(window["still"])
        let embed = try items(PetPage.url(pack: "cat", theme: "neon", scheme: "dark", hud: "off", mode: .embed))
        XCTAssertEqual(embed["embed"], "1")
        XCTAssertNil(embed["still"])
        XCTAssertEqual(embed["hud"], "off")
        let still = try items(PetPage.url(pack: "bit", theme: "minimal", scheme: "light", hud: "off", mode: .still))
        XCTAssertEqual(still["still"], "1")
        XCTAssertNil(still["embed"])
    }

    func testThumbnailsAcceptOnlyPNGDataURLs() throws {
        // A 1x1 transparent PNG.
        let png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        XCTAssertNotNil(PetThumbnails.image(fromDataURL: "data:image/png;base64," + png))
        for bad in ["", "data:image/jpeg;base64," + png, "data:image/png;base64,", "data:image/png;base64,@@@@", "https://example.com/x.png", png,
                    "data:image/png;base64," + String(repeating: "A", count: 8_100_000)] {
            XCTAssertNil(PetThumbnails.image(fromDataURL: bad), String(bad.prefix(40)))
        }
    }

    func testThumbnailsAreCompleteOnlyForTheLookTheyWereMadeFor() {
        let thumbs = PetThumbnails()
        let pack = PetResources.Pack(id: "gauge", name: "量量", renderer: "three", directory: URL(fileURLWithPath: "/nonexistent"), builtin: true, stage: CGSize(width: 240, height: 260))
        XCTAssertFalse(thumbs.isComplete(for: [pack], theme: "aurora", scheme: "light"))
        XCTAssertTrue(thumbs.isComplete(for: [], theme: "", scheme: ""), "nothing to draw is complete")
    }
}

final class PetHooksTests: XCTestCase {
    private var tmp: URL!

    override func setUpWithError() throws {
        tmp = FileManager.default.temporaryDirectory.appendingPathComponent("pet-hooks-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: tmp) }

    func testTheCommandPrintsConfigurationAndNeverAppliesIt() {
        let project = URL(fileURLWithPath: "/Users/me/My Projects/it's here")
        let source = PetHooks.command(target: "claude", project: project, resources: nil, port: 8769)
        XCTAssertEqual(source, "cd '/Users/me/My Projects/it'\\''s here' && python3 -m agent_meter pet hooks claude")
        XCTAssertEqual(PetHooks.command(target: "codex", project: nil, resources: nil, port: 8769), "python3 -m agent_meter pet hooks codex")
        XCTAssertTrue(PetHooks.command(target: "claude", project: project, resources: nil, port: 18769).hasSuffix("pet --port 18769 hooks claude"))
    }

    func testTheBundledBackendIsUsedWhenItIsThere() throws {
        let backend = tmp.appendingPathComponent("backend")
        try FileManager.default.createDirectory(at: backend, withIntermediateDirectories: true)
        let executable = backend.appendingPathComponent("agent-meter-backend")
        try "#!/bin/sh\n".write(to: executable, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: executable.path)
        let command = PetHooks.command(target: "claude", project: URL(fileURLWithPath: "/dev/null"), resources: tmp, port: 8769)
        XCTAssertEqual(command, "'\(executable.path)' pet hooks claude")
        // Present but not executable: fall back to the source checkout.
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: executable.path)
        XCTAssertTrue(PetHooks.command(target: "claude", project: URL(fileURLWithPath: "/p"), resources: tmp, port: 8769).hasPrefix("cd '/p'"))
    }
}

final class BackendPortTests: XCTestCase {
    func testOnlySaneUnprivilegedPortsOverrideTheDefault() {
        XCTAssertEqual(BackendClient.defaultPort, 8769)
        XCTAssertEqual(BackendClient.port(from: [:]), 8769)
        XCTAssertEqual(BackendClient.port(from: ["AGENT_METER_PORT": "18769"]), 18769)
        for bad in ["", "abc", "80", "1023", "65536", "-1", "8769.5", "0x2000"] {
            XCTAssertEqual(BackendClient.port(from: ["AGENT_METER_PORT": bad]), 8769, bad)
        }
    }
}
