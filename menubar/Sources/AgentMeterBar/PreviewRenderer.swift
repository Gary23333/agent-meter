import AppKit
import SwiftUI

/// `AgentMeterBar --preview snapshot.json outDir` renders every tab in light
/// and dark appearance to PNG, without contacting the backend.
@MainActor
enum PreviewRenderer {
    static func run(snapshot path: String, outDir: String) {
        guard let data = FileManager.default.contents(atPath: path),
              let json = try? JSONDecoder().decode(JSON.self, from: data) else {
            FileHandle.standardError.write("cannot read snapshot\n".data(using: .utf8)!)
            exit(1)
        }
        let store = UsageStore.shared
        store.preview(Snapshot(json))
        PanelView.expandForPreview = true
        try? FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)

        let snap = Snapshot(json)
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

        // Every theme; aurora keeps the original file names, others get a prefix.
        var jobs: [(PanelTheme, Tab, NSAppearance.Name)] = []
        for theme in PanelTheme.allCases {
            for tab in Tab.allCases { for a in [NSAppearance.Name.aqua, .darkAqua] { jobs.append((theme, tab, a)) } }
        }
        let savedTheme = store.theme
        func next() {
            guard !jobs.isEmpty else { store.theme = savedTheme; exit(0) }
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
        next()
    }
}
