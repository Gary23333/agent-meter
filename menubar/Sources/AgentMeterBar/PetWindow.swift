import AppKit
import WebKit

// MARK: - Messages from the web page

struct PetRect: Equatable {
    let kind: String
    let rect: CGRect
}

enum PetAction: Equatable {
    case openPanel(tab: String?)

    static let tabs: Set<String> = ["accounts", "apps", "forecast", "usage", "pet", "collection"]

    static func parse(_ raw: Any?) -> PetAction? {
        guard let d = raw as? [String: Any], d["kind"] as? String == "open_panel" else { return nil }
        let tab = d["tab"] as? String
        return .openPanel(tab: tab.flatMap { tabs.contains($0) ? $0 : nil })
    }
}

/// What the page tells the host. Parsing is strict and total: anything unexpected becomes nil and is ignored.
enum PetMessage: Equatable {
    case ready(pack: String?, problem: String?)
    case rects([PetRect], size: CGSize?)
    case bubbleShown(id: String)
    case action(PetAction)
    case hudClick
    case sessionClick(app: String)
    case refreshRequest
    case petClick
    case error(String)

    private static func number(_ v: Any?) -> Double? { PetJSON.number(v) }

    static func parse(_ body: Any) -> PetMessage? {
        guard let m = body as? [String: Any], let type = m["type"] as? String else { return nil }
        switch type {
        case "ready":
            return .ready(pack: m["pack"] as? String, problem: m["problem"] as? String)
        case "rects":
            let rects: [PetRect] = (m["rects"] as? [[String: Any]] ?? []).prefix(8).compactMap { r in
                guard let kind = r["kind"] as? String, let x = number(r["x"]), let y = number(r["y"]),
                      let w = number(r["w"]), let h = number(r["h"]), w >= 0, h >= 0, w <= 4000, h <= 4000,
                      abs(x) <= 8000, abs(y) <= 8000 else { return nil }
                return PetRect(kind: kind, rect: CGRect(x: x, y: y, width: w, height: h))
            }
            var size: CGSize?
            if let s = m["size"] as? [String: Any], let w = number(s["w"]), let h = number(s["h"]) { size = CGSize(width: w, height: h) }
            return .rects(rects, size: size)
        case "bubble-shown":
            guard let id = m["id"] as? String, !id.isEmpty, id.count <= 200 else { return nil }
            return .bubbleShown(id: id)
        case "bubble-click", "action":
            return PetAction.parse(m["action"]).map { .action($0) }
        case "hud-click": return .hudClick
        case "session-click":
            guard let app = m["app"] as? String, !app.isEmpty, app.count <= 64 else { return nil }
            return .sessionClick(app: app)
        case "refresh-request": return .refreshRequest
        case "pet-click": return .petClick
        case "error": return .error(String((m["message"] as? String ?? "unknown").prefix(300)))
        default: return nil
        }
    }
}

/// Reminders already shown are dropped before the frame reaches the page (the page itself dedupes only
/// within a session; this is what survives restarts, the same way Notifier remembers its keys).
enum PetFrameFilter {
    static func fresh(_ frame: [String: Any], shown: Set<String>) -> [String: Any] {
        var out = frame
        if let reminders = frame["reminders"] as? [[String: Any]] {
            out["reminders"] = reminders.filter { !shown.contains($0["id"] as? String ?? "") }
        }
        return out
    }
}

/// Forwards script messages to a handler without keeping its owner alive (WKUserContentController retains its
/// message handlers, so the handler must capture its owner weakly).
final class PetMessageProxy: NSObject, WKScriptMessageHandler {
    private let handler: @MainActor (Any) -> Void

    init(_ handler: @escaping @MainActor (Any) -> Void) { self.handler = handler }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        let body = message.body
        DispatchQueue.main.async { [handler] in MainActor.assumeIsolated { handler(body) } }
    }
}

// MARK: - Window

/// Transparent, always-on-top, never key: it floats over everything without taking focus from the user.
@MainActor
final class PetPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }

    init(size: NSSize) {
        super.init(contentRect: NSRect(origin: .zero, size: size), styleMask: [.borderless, .nonactivatingPanel],
                   backing: .buffered, defer: false)
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        level = .floating
        collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle]
        isReleasedWhenClosed = false
        hidesOnDeactivate = false
        animationBehavior = .none
        acceptsMouseMovedEvents = true
        isMovableByWindowBackground = false
        ignoresMouseEvents = false
    }
}

/// Sits above the web view and owns every mouse interaction (hover, click, drag, right-click) so the page only
/// has to draw. Coordinates are top-left based, like the page's.
@MainActor
final class PetInputView: NSView {
    var onMove: ((CGPoint) -> Void)?
    var onLeave: (() -> Void)?
    var onClick: ((CGPoint) -> Void)?
    var onDoubleClick: ((CGPoint) -> Void)?
    var onContext: ((NSEvent) -> Void)?
    var onDragBegan: (() -> Void)?
    var onDragEnded: (() -> Void)?
    /// `.agentpet` files dragged onto the window (installation is the controller's job).
    var onDropFiles: (([URL]) -> Void)?
    /// Interactive regions reported by the page; empty means "everything" until the first report.
    var hitRects: [CGRect] = []

    private var startMouse = NSPoint.zero
    private var startOrigin = NSPoint.zero
    private var dragging = false
    private var tracking: NSTrackingArea?

    override var isFlipped: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let tracking { removeTrackingArea(tracking) }
        let area = NSTrackingArea(rect: bounds, options: [.activeAlways, .mouseMoved, .mouseEnteredAndExited, .inVisibleRect], owner: self, userInfo: nil)
        addTrackingArea(area)
        tracking = area
    }

    func isInteractive(_ point: CGPoint, slop: CGFloat = 6) -> Bool {
        hitRects.isEmpty || hitRects.contains { $0.insetBy(dx: -slop, dy: -slop).contains(point) }
    }

    private func local(_ event: NSEvent) -> CGPoint { convert(event.locationInWindow, from: nil) }

    override func mouseMoved(with event: NSEvent) { onMove?(local(event)) }
    override func mouseExited(with event: NSEvent) { onLeave?() }

    override func mouseDown(with event: NSEvent) {
        guard let window else { return }
        startMouse = NSEvent.mouseLocation
        startOrigin = window.frame.origin
        dragging = false
    }

    override func mouseDragged(with event: NSEvent) {
        guard let window else { return }
        let now = NSEvent.mouseLocation
        if !dragging {
            guard hypot(now.x - startMouse.x, now.y - startMouse.y) > 3 else { return }
            dragging = true
            onDragBegan?()
        }
        window.setFrameOrigin(NSPoint(x: startOrigin.x + now.x - startMouse.x, y: startOrigin.y + now.y - startMouse.y))
    }

    override func mouseUp(with event: NSEvent) {
        if dragging {
            dragging = false
            onDragEnded?()
        } else if event.clickCount >= 2 {
            onDoubleClick?(local(event))
        } else {
            onClick?(local(event))
        }
    }

    override func rightMouseDown(with event: NSEvent) { onContext?(event) }

    // MARK: File drops (.agentpet)

    private static func droppedURLs(_ sender: NSDraggingInfo) -> [URL] {
        (sender.draggingPasteboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL]) ?? []
    }

    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        PetInstaller.accepts(Self.droppedURLs(sender)) ? .copy : []
    }

    override func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation {
        PetInstaller.accepts(Self.droppedURLs(sender)) ? .copy : []
    }

    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        let urls = Self.droppedURLs(sender)
        guard PetInstaller.accepts(urls) else { return false }
        onDropFiles?(urls)
        return true
    }
}
