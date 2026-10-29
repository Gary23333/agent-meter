import AppKit
import SwiftUI

/// 独立报告窗口（单例），写法与 PricesWindow 一致。
@MainActor
enum ReportWindow {
    private static var window: NSWindow?
    private static let delegate = ReleaseOnClose()

    private final class ReleaseOnClose: NSObject, NSWindowDelegate {
        func windowWillClose(_ notification: Notification) {
            // Drop SwiftUI observation and backing surfaces when the report closes.
            ReportWindow.window?.contentViewController = nil
            ReportWindow.window = nil
        }
    }

    static func show() {
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 800),
                             styleMask: [.titled, .closable, .resizable, .miniaturizable],
                             backing: .buffered, defer: false)
            w.title = "用量报告与分享"
            w.isReleasedWhenClosed = false
            w.delegate = delegate
            // 用 hosting controller 挂载：手挂 contentView 时 AppKit 桥接控件
            // （分段选择器等）拿不到点击/动作，纯 SwiftUI 手势却正常。
            let host = NSHostingController(rootView: ReportView().environment(UsageStore.shared))
            w.contentViewController = host
            w.minSize = NSSize(width: 820, height: 640)
            w.center()
            window = w
        }
        StatusBarController.shared.closePanel()
        guard let window else { return }
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
        // 面板刚关闭时窗口往往还不是 key，点击会被吞掉；accessory 应用
        // 单靠 NSApp.activate 可能延迟，这里用 NSRunningApplication 立即抢焦点，
        // 并在下一轮 runloop 与面板收起后再补两次。
        activate(window)
        DispatchQueue.main.async { [weak window] in
            guard let window else { return }
            activate(window)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { [weak window] in
                guard let window else { return }
                activate(window)
            }
        }
    }

    private static func activate(_ window: NSWindow) {
        NSApp.activate(ignoringOtherApps: true)
        NSRunningApplication.current.activate(options: [.activateAllWindows, .activateIgnoringOtherApps])
        window.makeKey()
    }
}
