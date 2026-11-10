import XCTest
@testable import AgentMeterBar

/// The desktop pet host: URL routing and file-serving rules (security relevant), pack discovery, the messages the
/// page may send, preferences, and the reminder keys the pet shares with the system notifications.
final class PetPathTests: XCTestCase {
    private var tmp: URL!

    override func setUpWithError() throws {
        tmp = FileManager.default.temporaryDirectory.appendingPathComponent("pet-tests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: tmp)
    }

    private func write(_ relative: String, _ text: String = "{}") throws {
        let url = tmp.appendingPathComponent(relative)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try text.write(to: url, atomically: true, encoding: .utf8)
    }

    func testRoutesAcceptOnlyOurSchemeHostAndShapes() {
        XCTAssertEqual(PetPath.route(for: URL(string: "agentpet://app/runtime/index.html")!), .runtime("index.html"))
        XCTAssertEqual(PetPath.route(for: URL(string: "agentpet://app/runtime/js/main.js?x=1")!), .runtime("js/main.js"))
        XCTAssertEqual(PetPath.route(for: URL(string: "agentpet://app/pack/gauge/sprites/idle.png")!), .pack(id: "gauge", path: "sprites/idle.png"))
        for bad in ["http://app/runtime/x.js", "agentpet://evil/runtime/x.js", "agentpet://app/", "agentpet://app/other/x",
                    "agentpet://app/pack/Bad%20Id/x.json", "agentpet://app/pack/gauge", "agentpet://app/runtime"] {
            XCTAssertNil(PetPath.route(for: URL(string: bad)!), bad)
        }
    }

    func testResolveServesOnlyRegularAllowedFilesInsideTheBase() throws {
        try write("base/ok.json")
        try write("base/sub/x.png", "png")
        try write("base/.hidden.json")
        try write("base/script.sh", "#!/bin/sh")
        try write("base/page.svg", "<svg/>")
        try write("outside/secret.json", "secret")
        try FileManager.default.createDirectory(at: tmp.appendingPathComponent("base/folder.json"), withIntermediateDirectories: true)
        try FileManager.default.createSymbolicLink(at: tmp.appendingPathComponent("base/link.json"), withDestinationURL: tmp.appendingPathComponent("outside/secret.json"))
        try FileManager.default.createSymbolicLink(at: tmp.appendingPathComponent("base/linkdir"), withDestinationURL: tmp.appendingPathComponent("outside"))
        let base = tmp.appendingPathComponent("base")

        XCTAssertNotNil(PetPath.resolve(base: base, relative: "ok.json"))
        XCTAssertNotNil(PetPath.resolve(base: base, relative: "sub/x.png"))
        let refused = ["../outside/secret.json", "sub/../../outside/secret.json", "%2e%2e/outside/secret.json", "/etc/hosts", "", ".hidden.json",
                       "script.sh", "page.svg", "folder.json", "missing.json", "link.json", "linkdir/secret.json", "ok.json\0.png", "a\\b.json", "sub//x.png", "sub/./x.png"]
        for relative in refused { XCTAssertNil(PetPath.resolve(base: base, relative: relative), relative) }
    }

    func testDecodedDotSegmentsInURLsNeverReachTheFileSystem() throws {
        try write("base/runtime/index.html", "<html/>")
        try write("secret.json", "secret")
        let handler = PetSchemeHandler(root: { self.tmp.appendingPathComponent("base") }, packs: { [] })
        XCTAssertNotNil(handler.file(for: URL(string: "agentpet://app/runtime/index.html")!))
        XCTAssertNil(handler.file(for: URL(string: "agentpet://app/runtime/%2e%2e/%2e%2e/secret.json")!))
        XCTAssertNil(handler.file(for: URL(string: "agentpet://app/runtime/..%2fsecret.json")!))
        XCTAssertNil(handler.file(for: URL(string: "agentpet://app/pack/nope/pet.json")!))
    }

    func testPacksAreServedFromTheirOwnFolderOnly() throws {
        try write("one/gauge/pet.json", #"{"format":"agentmeter-pet/1","id":"gauge","renderer":"three"}"#)
        try write("one/gauge/avatar.json")
        try write("one/other/pet.json", "{}")
        let pack = PetResources.Pack(id: "gauge", name: "量量", renderer: "three", directory: tmp.appendingPathComponent("one/gauge"), builtin: true, stage: CGSize(width: 240, height: 260))
        let handler = PetSchemeHandler(root: { nil }, packs: { [pack] })
        XCTAssertNotNil(handler.file(for: URL(string: "agentpet://app/pack/gauge/avatar.json")!))
        XCTAssertNil(handler.file(for: URL(string: "agentpet://app/pack/gauge/../other/pet.json")!))
        XCTAssertNil(handler.file(for: URL(string: "agentpet://app/pack/other/pet.json")!))
    }

    func testContentSecurityPolicyForbidsEverythingButTheScheme() {
        let policy = PetSchemeHandler.policy
        XCTAssertTrue(policy.contains("default-src 'none'"))
        XCTAssertTrue(policy.contains("connect-src agentpet:"))
        XCTAssertFalse(policy.contains("http"))
        XCTAssertFalse(policy.contains("'unsafe-eval'"))
    }

    // MARK: discovery

    private func manifest(_ id: String, name: String = "名", renderer: String = "three", extra: String = "") -> String {
        #"{"format":"agentmeter-pet/1","id":"\#(id)","name":"\#(name)","renderer":"\#(renderer)","stage":{"width":300,"height":310}\#(extra)}"#
    }

    func testDiscoveryKeepsOnlySaneFolderPacksAndUserPacksOverrideBuiltIns() throws {
        try write("builtin/gauge/pet.json", manifest("gauge", name: "内置"))
        try write("builtin/blob/pet.json", manifest("blob"))
        try write("builtin/wrong/pet.json", manifest("not-wrong"))               // id must equal the folder name
        try write("builtin/Bad Id/pet.json", manifest("Bad Id"))
        try write("builtin/broken/pet.json", "{nope")
        try write("builtin/old/pet.json", #"{"format":"agentmeter-pet/0","id":"old","renderer":"three"}"#)
        try write("builtin/odd/pet.json", manifest("odd", renderer: "svg"))
        try write("user/gauge/pet.json", manifest("gauge", name: "我的量量"))
        try write("user/mine/pet.json", manifest("mine", renderer: "sprite"))
        try FileManager.default.createSymbolicLink(at: tmp.appendingPathComponent("user/linked"), withDestinationURL: tmp.appendingPathComponent("builtin/blob"))

        let packs = PetResources.discover(roots: [(tmp.appendingPathComponent("builtin"), true), (tmp.appendingPathComponent("user"), false)])
        XCTAssertEqual(packs.map(\.id), ["blob", "gauge", "mine"])
        let gauge = try XCTUnwrap(packs.first { $0.id == "gauge" })
        XCTAssertEqual(gauge.name, "我的量量")
        XCTAssertFalse(gauge.builtin)
        XCTAssertEqual(gauge.stage, CGSize(width: 300, height: 310))
        XCTAssertEqual(packs.first { $0.id == "mine" }?.renderer, "sprite")
    }

    func testStageSizeIsClamped() throws {
        try write("p/huge/pet.json", manifest("huge", extra: "").replacingOccurrences(of: #""width":300,"height":310"#, with: #""width":9000,"height":3"#))
        let pack = try XCTUnwrap(PetResources.discover(roots: [(tmp.appendingPathComponent("p"), false)]).first)
        XCTAssertEqual(pack.stage, CGSize(width: 480, height: 120))
    }

    func testIDValidation() {
        for good in ["gauge", "a1", "my-pet-2"] { XCTAssertTrue(PetResources.validID(good), good) }
        for bad in ["", "a", "-x", "Ab", "has space", "../x", "x_y", String(repeating: "a", count: 40)] { XCTAssertFalse(PetResources.validID(bad), bad) }
    }

    func testTheShippedPresetsAreDiscoverable() throws {
        let presets = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("pets/presets")
        let ids = Set(PetResources.discover(roots: [(presets, true)]).map(\.id))
        XCTAssertTrue(ids.isSuperset(of: ["gauge", "blob", "bot", "cat", "tibo", "bit"]), "\(ids)")
    }
}

final class PetMessageTests: XCTestCase {
    func testWellFormedMessages() {
        XCTAssertEqual(PetMessage.parse(["type": "ready", "pack": "gauge"]), .ready(pack: "gauge", problem: nil))
        XCTAssertEqual(PetMessage.parse(["type": "bubble-shown", "id": "low|codex|primary|1|20"]), .bubbleShown(id: "low|codex|primary|1|20"))
        XCTAssertEqual(PetMessage.parse(["type": "hud-click"]), .hudClick)
        XCTAssertEqual(PetMessage.parse(["type": "refresh-request"]), .refreshRequest)
        XCTAssertEqual(PetMessage.parse(["type": "pet-click"]), .petClick)
        XCTAssertEqual(PetMessage.parse(["type": "error", "message": "boom"]), .error("boom"))
        XCTAssertEqual(PetMessage.parse(["type": "bubble-click", "action": ["kind": "open_panel", "tab": "forecast"]]), .action(.openPanel(tab: "forecast")))
        XCTAssertEqual(PetMessage.parse(["type": "action", "action": ["kind": "open_panel", "tab": "bogus"]]), .action(.openPanel(tab: nil)))
    }

    func testRectsAcceptIntegersAndRejectNonsense() {
        let ok: [String: Any] = ["type": "rects", "size": ["w": 310, "h": 404],
                                 "rects": [["kind": "pet", "x": 1, "y": 0, "w": 120.5, "h": 200], ["kind": "hud", "x": 90, "y": 380, "w": 130, "h": 24]]]
        guard case .rects(let rects, let size)? = PetMessage.parse(ok) else { return XCTFail("not parsed") }
        XCTAssertEqual(rects.count, 2)
        XCTAssertEqual(rects[0].rect, CGRect(x: 1, y: 0, width: 120.5, height: 200))        // x = 1 is a number, not a Bool
        XCTAssertEqual(size, CGSize(width: 310, height: 404))
        let junk: [String: Any] = ["type": "rects", "rects": [["kind": "pet", "x": true, "y": 0, "w": 10, "h": 10],
                                                              ["kind": "pet", "x": 0, "y": 0, "w": -5, "h": 10],
                                                              ["kind": "pet", "x": 0, "y": 0, "w": 99999, "h": 10],
                                                              ["kind": 3, "x": 0, "y": 0, "w": 1, "h": 1], ["x": 0]]]
        guard case .rects(let none, _)? = PetMessage.parse(junk) else { return XCTFail("not parsed") }
        XCTAssertTrue(none.isEmpty)
        let many = (0..<30).map { ["kind": "pet", "x": $0, "y": 0, "w": 1, "h": 1] as [String: Any] }
        guard case .rects(let capped, _)? = PetMessage.parse(["type": "rects", "rects": many]) else { return XCTFail("not parsed") }
        XCTAssertEqual(capped.count, 8)
    }

    func testUnknownOrMalformedMessagesAreIgnored() {
        for body in [["type": "fly-to-the-moon"], ["nothing": 1], ["type": 3], ["type": "bubble-shown"], ["type": "bubble-shown", "id": ""],
                     ["type": "bubble-click", "action": ["kind": "format_disk"]], ["type": "action"]] as [[String: Any]] {
            XCTAssertNil(PetMessage.parse(body), "\(body)")
        }
        XCTAssertNil(PetMessage.parse("a string"))
        XCTAssertNil(PetMessage.parse(42))
        XCTAssertEqual(PetMessage.parse(["type": "error", "message": String(repeating: "x", count: 900)]), .error(String(repeating: "x", count: 300)))
    }

    func testAlreadyShownRemindersAreFilteredOutOfFrames() {
        let frame: [String: Any] = ["state": "idle", "reminders": [["id": "a", "text": "A"], ["id": "b", "text": "B"], ["text": "no id"]]]
        let fresh = PetFrameFilter.fresh(frame, shown: ["a"])
        let ids = (fresh["reminders"] as? [[String: Any]] ?? []).map { $0["id"] as? String }
        XCTAssertEqual(ids, ["b", nil])
        XCTAssertEqual(fresh["state"] as? String, "idle")
        XCTAssertEqual((PetFrameFilter.fresh(["state": "x"], shown: ["a"]))["state"] as? String, "x")
    }
}

@MainActor
final class PetPrefsTests: XCTestCase {
    private func defaults() -> UserDefaults {
        let name = "pet-prefs-\(UUID().uuidString)"
        let d = UserDefaults(suiteName: name)!
        addTeardownBlock { d.removePersistentDomain(forName: name) }
        return d
    }

    func testDefaultsAreConservative() {
        let prefs = PetPrefs(defaults: defaults())
        XCTAssertFalse(prefs.enabled)                       // the pet is opt-in
        XCTAssertEqual(prefs.packID, "gauge")
        XCTAssertEqual(prefs.size, .medium)
        XCTAssertEqual(prefs.hud, .pill)
        XCTAssertTrue(prefs.followCursor)
        XCTAssertFalse(prefs.calm)
        XCTAssertFalse(prefs.takeoverAlerts)                // system notifications stay unless the user opts in
        XCTAssertEqual(prefs.breakMinutes, 120)
        XCTAssertNil(prefs.quietHours)
        XCTAssertEqual(prefs.energySource, "auto")
        XCTAssertNil(prefs.origin)
    }

    func testChangesPersistAndBadStoredValuesFallBack() {
        let d = defaults()
        let prefs = PetPrefs(defaults: d)
        prefs.enabled = true
        prefs.packID = "cat"
        prefs.size = .large
        prefs.hud = .full
        prefs.quietHours = "23:00-08:00"
        prefs.origin = CGPoint(x: 120, y: 48)
        let again = PetPrefs(defaults: d)
        XCTAssertEqual([again.enabled, again.followCursor], [true, true])
        XCTAssertEqual(again.packID, "cat")
        XCTAssertEqual(again.size, .large)
        XCTAssertEqual(again.hud, .full)
        XCTAssertEqual(again.quietHours, "23:00-08:00")
        XCTAssertEqual(again.origin, CGPoint(x: 120, y: 48))
        d.set("gigantic", forKey: "petSize")
        d.set("sparkles", forKey: "petHUD")
        XCTAssertEqual(PetPrefs(defaults: d).size, .medium)
        XCTAssertEqual(PetPrefs(defaults: d).hud, .pill)
        again.origin = nil
        XCTAssertNil(PetPrefs(defaults: d).origin)
    }

    func testBrainPreferencesMatchTheBackendContract() {
        let prefs = PetPrefs(defaults: defaults())
        let body = prefs.brainPreferences(lowQuotaThreshold: 30)
        XCTAssertEqual(Set(body.keys), ["low_quota_threshold", "energy_source", "quiet_hours", "break_after_minutes"])
        XCTAssertEqual(body["low_quota_threshold"] as? Double, 30)
        XCTAssertEqual(body["energy_source"] as? String, "auto")
        XCTAssertTrue(body["quiet_hours"] is NSNull)
        prefs.quietHours = "22:00-07:00"
        XCTAssertEqual(prefs.brainPreferences(lowQuotaThreshold: 20)["quiet_hours"] as? String, "22:00-07:00")
        XCTAssertTrue(PetSize.allCases.map(\.scale).sorted() == PetSize.allCases.map(\.scale))
    }
}

@MainActor
final class PetFrameTests: XCTestCase {
    func testOfflineFrameSaysDisconnectedNotEmpty() {
        let frame = PetController.offlineFrame(now: Date(timeIntervalSince1970: 1000))
        XCTAssertEqual(frame["state"] as? String, "offline")
        XCTAssertEqual((frame["energy"] as? [String: Any])?["known"] as? Bool, false)
        XCTAssertEqual((frame["energy"] as? [String: Any])?["tone"] as? String, "unknown")
        XCTAssertEqual((frame["reminders"] as? [Any])?.count, 0)
        XCTAssertNoThrow(try JSONSerialization.data(withJSONObject: frame))
    }

    func testDemoFramesAreValidAndHonest() throws {
        for state in ["idle", "working", "busy", "alarm", "tired", "exhausted", "offline", "confused", "alert", "sleeping", "focus"] {
            let frame = PetController.demoFrame(state: state, now: Date(timeIntervalSince1970: 1000))
            XCTAssertEqual(frame["state"] as? String, state)
            XCTAssertNoThrow(try JSONSerialization.data(withJSONObject: frame), state)
        }
        let alarm = PetController.demoFrame(state: "alarm")["energy"] as? [String: Any]
        XCTAssertEqual(alarm?["tone"] as? String, "critical")
        XCTAssertEqual(alarm?["remaining"] as? Double, 4)
        let unknown = PetController.demoFrame(state: "offline")["energy"] as? [String: Any]
        XCTAssertEqual(unknown?["known"] as? Bool, false)
        XCTAssertNil(unknown?["remaining"])                    // unknown is never shown as 0
        XCTAssertEqual((PetController.demoFrame(state: "alert")["reminders"] as? [Any])?.count, 1)
    }
}

/// The pet's reminders and the system notifications must name the same events: both sides are checked against
/// the same fixture, with expectations derived by hand from Notifier.swift (see tests/test_pet.py).
@MainActor
final class PetReminderParityTests: XCTestCase {
    func testNotifierProducesExactlyTheKeysThePythonBrainExpects() throws {
        let fixture = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("tests/fixtures/pet_reminder_parity.json")
        let root = try JSONDecoder().decode(JSON.self, from: Data(contentsOf: fixture))
        let snapshot = Snapshot(root["snapshot"])
        let now = Date(timeIntervalSince1970: try XCTUnwrap(root["now"].double))
        let keys = Notifier.shared.alerts(snapshot, threshold: try XCTUnwrap(root["threshold"].double), now: now).map(\.key).sorted()
        let expected = [
            "low|codex|primary|1760009000|20", "low|codex|secondary|1760259200|5", "low|claude|limit5h|1760001000|0",
            "low|zcode|mcp|1761728000|5", "card|codex|1760018000|1", "card|codex|1760172800|3",
            "credit|minimax_design|1760108000|3", "renew|minimax_design|2025-10-11|3", "member|dreamina|2025-10-12|7",
            "tiboWindow|1760007200|open", "tiboLanded|p-9",
        ].sorted()
        XCTAssertEqual(keys, expected)
    }
}
