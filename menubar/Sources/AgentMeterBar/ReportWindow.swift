import AppKit
import SwiftUI

/// 独立报告窗口（单例），写法与 PricesWindow 一致。
@MainActor
enum ReportWindow {
    private static var window: NSWindow?

    static func show() {
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 800),
                             styleMask: [.titled, .closable, .resizable, .miniaturizable],
                             backing: .buffered, defer: false)
            w.title = "用量报告与分享"
            w.isReleasedWhenClosed = false
            w.contentView = NSHostingView(rootView: ReportView().environment(UsageStore.shared))
            w.minSize = NSSize(width: 820, height: 640)
            w.center()
            window = w
        }
        StatusBarController.shared.closePanel()
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
    }
}
