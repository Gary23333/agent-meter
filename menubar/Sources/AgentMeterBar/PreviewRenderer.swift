import AppKit
import SwiftUI

/// `AgentMeterBar --preview snapshot.json outDir` renders every tab in light
/// and dark appearance to PNG, without contacting the backend.
@MainActor
enum PreviewRenderer {
    /// Representative activity rows covering every status and granularity.
    private static func previewActivity() {
        func ts(_ seconds: Double) -> JSON {
            .object(["epoch_seconds": .number(Double(Date().timeIntervalSince1970) - seconds)])
        }
        func row(_ fields: [String: JSON]) -> JSON {
            .object(fields)
        }
        let now = Double(Date().timeIntervalSince1970)
        let activities: [JSON] = [
            row(["app": .string("zcode"), "granularity": .string("turn"), "status": .string("running"),
                 "status_basis": .string("recency"), "project_alias": .string("NEW-agent 统计"),
                 "project_path": .string("/Users/u/项目/NEW-agent 统计"), "session_id": .string("sess_main"),
                 "subagent": .bool(false), "started_at": ts(5400), "last_event_at": ts(20),
                 "last_model": .string("account:bigmodel/GLM-5.3-Flash"), "requests": .number(98),
                 "tokens": .object(["fresh_input": .number(1200000), "output": .number(42000),
                                    "reasoning": .number(8000), "cache_read": .number(26000000),
                                    "cache_write": .number(900000), "total_tokens": .number(28584007)]),
                 "estimated_cost_usd": .null, "notes": .string("turn_status_not_session_status"),
                 "turn_statuses": .object(["completed": .number(7)]),
                 "last_turn_status": .string("completed"), "turns": .number(8),
                 "recent_turns": .array([
                    .object(["turn": .string("7"), "started_at": ts(600), "ended_at": ts(120),
                             "status": .string("completed"), "model": .string("GLM-5.3-Flash"),
                             "tokens": .number(3100000), "steps": .number(5)]),
                    .object(["turn": .string("8"), "started_at": ts(90), "ended_at": .null,
                             "status": .string("unknown"), "model": .string("GLM-5.3-Flash"),
                             "tokens": .number(260000), "steps": .null]),
                 ])]),
            row(["app": .string("deepseek_harness"), "granularity": .string("turn_steps"),
                 "status": .string("completed"), "status_basis": .string("explicit_event"),
                 "project_alias": .string("1020-华为"), "project_path": .string("/Users/u/proj/1020-华为"),
                 "session_id": .string("session-df893f04"), "subagent": .bool(false),
                 "started_at": ts(70000), "last_event_at": ts(69000),
                 "last_model": .string("deepseek-flash"), "requests": .number(85),
                 "tokens": .object(["fresh_input": .number(900000), "output": .number(61000),
                                    "reasoning": .number(24000), "cache_read": .number(2000000),
                                    "cache_write": .number(0), "total_tokens": .number(2970954)]),
                 "estimated_cost_usd": .number(0.42), "notes": .string("turn_status_not_session_status"),
                 "turn_statuses": .object(["completed": .number(2), "cancelled": .number(1)]),
                 "last_turn_status": .string("completed"), "turns": .number(3),
                 "recent_turns": .array([])]),
            row(["app": .string("codex_images"), "granularity": .string("image_call"),
                 "status": .string("failed"), "status_basis": .string("explicit_event"),
                 "project_alias": .null, "project_path": .null, "session_id": .string("019e682a"),
                 "subagent": .bool(false), "started_at": ts(3000), "last_event_at": ts(2900),
                 "last_model": .null, "requests": .number(4),
                 "tokens": .null, "estimated_cost_usd": .null,
                 "notes": .string("call_status_not_whole_session"),
                 "turn_statuses": .object([:]), "last_turn_status": .null, "turns": .null,
                 "recent_turns": .array([]),
                 "calls": .number(4), "failed_calls": .number(1), "generating_calls": .number(0)]),
            row(["app": .string("kimi_desktop"), "granularity": .string("steps"),
                 "status": .string("suspected_ended"), "status_basis": .string("recency"),
                 "project_alias": .string("wd_workspace_bbe9353a165b"), "project_path": .null,
                 "session_id": .string("session_a7a2b363"), "subagent": .bool(true),
                 "started_at": ts(120000), "last_event_at": ts(5400),
                 "last_model": .string("kimi-code/k3"), "requests": .number(914),
                 "tokens": .object(["fresh_input": .number(62000000), "output": .number(1400000),
                                    "reasoning": .number(0), "cache_read": .number(34000000),
                                    "cache_write": .number(980000), "total_tokens": .number(97477171)]),
                 "estimated_cost_usd": .null, "notes": .string("turn_status_not_session_status"),
                 "turn_statuses": .object(["completed": .number(1)]),
                 "last_turn_status": .string("completed"), "turns": .number(1), "recent_turns": .array([])]),
            row(["app": .string("claude"), "granularity": .string("recent_activity"),
                 "status": .string("suspected_ended"), "status_basis": .string("recency"),
                 "project_alias": .string("0916-宝格丽烟花"), "project_path": .string("/Users/u/proj/0916"),
                 "session_id": .string("5e94bd54"), "subagent": .bool(false),
                 "started_at": ts(90000), "last_event_at": ts(36000),
                 "last_model": .string("claude-opus-5-5"), "requests": .number(41),
                 "tokens": .object(["fresh_input": .number(240000), "output": .number(31000),
                                    "reasoning": .number(12000), "cache_read": .number(4000000),
                                    "cache_write": .number(95000), "total_tokens": .number(4336718)]),
                 "estimated_cost_usd": .number(1.87), "notes": .string("recency_only_no_terminal_events"),
                 "turn_statuses": .object([:]), "last_turn_status": .null, "turns": .null, "recent_turns": .array([])]),
        ]
        let meta: [String: JSON] = [
            "zcode": .object(["status": .string("available"), "activities": .number(8)]),
            "codex_images": .object(["status": .string("available"), "activities": .number(3)]),
            "kimi": .object(["status": .string("available"), "activities": .number(2)]),
            "kimi_desktop": .object(["status": .string("available"), "activities": .number(6)]),
            "deepseek_harness": .object(["status": .string("available"), "activities": .number(4)]),
            "claude": .object(["status": .string("available"), "activities": .number(5)]),
            "gemini": .object(["status": .string("not_connected"), "reason": .string("gemini_chats_not_found"), "activities": .number(0)]),
            "opencode": .object(["status": .string("available"), "activities": .number(1)]),
        ]
        ActivityTracker.shared.preview(ActivityFeed(.object([
            "schema_version": .number(1),
            "generated_at": .object(["epoch_seconds": .number(now)]),
            "window_hours": .number(24), "idle_after_minutes": .number(15),
            "activities": .array(activities), "sources_meta": .object(meta),
        ])))
    }

    static func run(snapshot path: String, outDir: String) {
        guard let data = FileManager.default.contents(atPath: path),
              let json = try? JSONDecoder().decode(JSON.self, from: data) else {
            FileHandle.standardError.write("cannot read snapshot\n".data(using: .utf8)!)
            exit(1)
        }
        let store = UsageStore.shared
        store.preview(Snapshot(json))
        PanelView.expandForPreview = true
        previewActivity()
        try? FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)

        let snap = Snapshot(json)
        // Both presets and a no-cost variant, in every theme.
        if let report = ReportData.build(snapshot: snap, period: .week, now: Date()) {
            var hidden = ShareOptions.review
            hidden.costs = false
            for theme in PanelTheme.allCases {
                for (name, options) in [("compact", ShareOptions.compact), ("review", .review), ("no-cost", hidden)] {
                    if let png = ShareCardRenderer.pngData(data: report, theme: theme, options: options, scale: 2) {
                        try? png.write(to: URL(fileURLWithPath: outDir)
                            .appendingPathComponent("share-\(theme.rawValue)-\(name).png"))
                    }
                }
            }
        }
        if CommandLine.arguments.contains("--share-only") { exit(0) }

        // Dry-run alert rules now and at later times so expiry rules are exercised.
        var report = ""
        for days in [0.0, 10, 11.5, 13.2] {
            let at = Date().addingTimeInterval(days * 86400)
            report += "== now + \(days) days\n"
            for a in Notifier.shared.alerts(snap, threshold: 20, now: at) { report += "[\(a.key)] \(a.title)：\(a.body)\n" }
        }
        try? report.write(toFile: outDir + "/alerts.txt", atomically: true, encoding: .utf8)
        for appearance in [NSAppearance.Name.aqua, .darkAqua] {
            let items = snap.tickerItems(now: Date())
            let strip = HStack(spacing: 18) { ForEach(items) { TickerCell(item: $0) } }
                .padding(.horizontal, 8).frame(height: 24)
                .background(Color(nsColor: .windowBackgroundColor))
            let host = NSHostingView(rootView: strip)
            host.appearance = NSAppearance(named: appearance)
            host.frame.size = host.fittingSize
            host.layoutSubtreeIfNeeded()
            if let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) {
                host.cacheDisplay(in: host.bounds, to: rep)
                try? rep.representation(using: .png, properties: [:])?
                    .write(to: URL(fileURLWithPath: outDir).appendingPathComponent("ticker-\(appearance == .darkAqua ? "dark" : "light").png"))
            }
        }

        do {
            let host = NSHostingView(rootView: ConnectionsView().environment(store)
                .background(Color(nsColor: .windowBackgroundColor)))
            host.appearance = NSAppearance(named: .aqua)
            host.frame.size = host.fittingSize
            host.layoutSubtreeIfNeeded()
            if let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) {
                host.cacheDisplay(in: host.bounds, to: rep)
                try? rep.representation(using: .png, properties: [:])?
                    .write(to: URL(fileURLWithPath: outDir).appendingPathComponent("connections-light.png"))
            }
        }

        // Report window: renders the share-card preview so a layout-time
        // regression (the previous host-view measurement) fails this run.
        func renderReport(_ done: @escaping () -> Void) {            let host = NSHostingView(rootView: ReportView().environment(store))
            let window = NSWindow(contentRect: NSRect(x: -10000, y: -10000, width: 900, height: 800),
                                  styleMask: [.borderless], backing: .buffered, defer: false)
            window.appearance = NSAppearance(named: .aqua)
            window.contentView = host
            host.frame = NSRect(x: 0, y: 0, width: 900, height: 800)
            window.setContentSize(NSSize(width: 900, height: 800))
            window.orderFrontRegardless()
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                host.layoutSubtreeIfNeeded()
                if let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) {
                    host.cacheDisplay(in: host.bounds, to: rep)
                    try? rep.representation(using: .png, properties: [:])?
                        .write(to: URL(fileURLWithPath: outDir).appendingPathComponent("report-light.png"))
                }
                window.orderOut(nil)
                done()
            }
        }

        // Every theme; aurora keeps the original file names, others get a prefix.
        var jobs: [(PanelTheme, Tab, NSAppearance.Name)] = []
        for theme in PanelTheme.allCases {
            for tab in Tab.allCases { for a in [NSAppearance.Name.aqua, .darkAqua] { jobs.append((theme, tab, a)) } }
        }
        let savedTheme = store.theme
        let savedTab = UserDefaults.standard.object(forKey: "panelTab")
        func next() {
            guard !jobs.isEmpty else {
                store.theme = savedTheme
                UserDefaults.standard.set(savedTab, forKey: "panelTab")
                exit(0)
            }
            let (theme, tab, appearance) = jobs.removeFirst()
            store.theme = theme
            UserDefaults.standard.set(tab.rawValue, forKey: "panelTab")
            let host = NSHostingView(rootView: PanelView().environment(store)
                .background(Color(nsColor: .windowBackgroundColor)))
            let window = NSWindow(contentRect: NSRect(x: -10000, y: -10000, width: 400, height: 400),
                                  styleMask: [.borderless], backing: .buffered, defer: false)
            window.appearance = NSAppearance(named: appearance)
            window.contentView = host
            host.frame.size = host.fittingSize
            window.setContentSize(host.fittingSize)
            window.orderFrontRegardless()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                host.layoutSubtreeIfNeeded()
                if let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) {
                    host.cacheDisplay(in: host.bounds, to: rep)
                    let name = (theme == .aurora ? "" : theme.rawValue + "-") + "\(tab.rawValue)-\(appearance == .darkAqua ? "dark" : "light").png"
                    try? rep.representation(using: .png, properties: [:])?
                        .write(to: URL(fileURLWithPath: outDir).appendingPathComponent(name))
                }
                window.orderOut(nil)
                next()
            }
        }
        renderReport { next() }
    }
}
