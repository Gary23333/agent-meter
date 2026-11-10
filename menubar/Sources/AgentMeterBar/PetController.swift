import AppKit
import Observation
import WebKit

private final class ClosureMenuItem: NSMenuItem {
    private let handler: () -> Void

    init(_ title: String, checked: Bool = false, handler: @escaping () -> Void) {
        self.handler = handler
        super.init(title: title, action: #selector(fire), keyEquivalent: "")
        target = self
        state = checked ? .on : .off
    }

    required init(coder: NSCoder) { fatalError("not used") }

    @objc private func fire() { handler() }
}

/// Owns the desktop pet: the floating window, the web view that draws it, the loop that feeds it frames from the
/// backend, and every way the user can talk back (drag, click, menu). All state of the *pet* lives in the backend
/// brain (`GET /v1/pet`); this class only moves data and handles the operating system.
@MainActor
final class PetController: NSObject, WKNavigationDelegate {
    static let shared = PetController()

    private let prefs = PetPrefs.shared
    private let store = UsageStore.shared
    private var started = false
    private var panel: PetPanel?
    private var web: WKWebView?
    private var input: PetInputView?
    private var packs: [PetResources.Pack] = []
    private var loadedKey = ""
    private var ready = false
    private var pending: [String: Any]?
    private var monitors: [Any] = []
    private var dragging = false
    private var visible = true
    private var lastCursorSent = Date.distantPast
    private var cursorWasNear = false
    private var shown: [String: Double]
    private var lastState = ""
    private var demo: (state: String, out: String)?

    /// True while the pet is on screen and its page has loaded; Notifier uses it for "pet takes over alerts".
    private(set) var isActive = false

    private override init() {
        shown = UserDefaults.standard.dictionary(forKey: "petShown") as? [String: Double] ?? [:]
        super.init()
    }

    // MARK: Lifecycle

    func start() {
        guard !started else { return }
        started = true
        observe()
        NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.keepOnScreen() }
        }
        let workspace = NSWorkspace.shared.notificationCenter
        for name in [NSWorkspace.screensDidSleepNotification, NSWorkspace.willSleepNotification] {
            workspace.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in MainActor.assumeIsolated { self?.setVisible(false) } }
        }
        for name in [NSWorkspace.screensDidWakeNotification, NSWorkspace.didWakeNotification] {
            workspace.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in MainActor.assumeIsolated { self?.setVisible(true) } }
        }
        workspace.addObserver(forName: NSWorkspace.accessibilityDisplayOptionsDidChangeNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.pushPrefs() }
        }
    }

    /// Re-applies whenever a preference or the panel theme changes. Idempotent: it diffs against what is loaded.
    private func observe() {
        withObservationTracking { reconcile() } onChange: { [weak self] in
            DispatchQueue.main.async { MainActor.assumeIsolated { self?.observe() } }
        }
    }

    private func reconcile() {
        let enabled = prefs.enabled || demo != nil
        let packID = prefs.packID, size = prefs.size
        _ = (prefs.hud, prefs.followCursor, prefs.calm, prefs.breakMinutes, prefs.quietHours, prefs.energySource, prefs.takeoverAlerts)
        _ = (store.theme, store.lowQuotaThreshold)
        guard enabled else { teardown(); return }
        packs = PetResources.allPacks()
        ensureWindow()
        let key = "\(packID)|\(size.rawValue)"
        if key != loadedKey {
            loadedKey = key
            resizeWindow()
            loadPage()
        } else {
            pushPrefs()
            pushTheme()
        }
        if demo == nil { subscribeToFeed() }
    }

    private func teardown() {
        PetFeed.shared.unsubscribe(Self.feedID)
        removeMonitors()
        panel?.orderOut(nil)
        web?.configuration.userContentController.removeScriptMessageHandler(forName: "pet")
        panel = nil
        web = nil
        input = nil
        ready = false
        isActive = false
        loadedKey = ""
    }

    // MARK: Window

    private var currentPack: PetResources.Pack? { packs.first { $0.id == prefs.packID } ?? packs.first { $0.id == "gauge" } }

    private func windowSize() -> NSSize {
        let stage = currentPack?.stage ?? CGSize(width: 240, height: 260)
        let scale = prefs.size.scale
        return NSSize(width: max(300, stage.width * scale + 70), height: stage.height * scale + 34 + 110)
    }

    private func ensureWindow() {
        guard panel == nil else { return }
        let size = windowSize()
        let panel = PetPanel(size: size)

        let config = WKWebViewConfiguration()
        config.setURLSchemeHandler(PetSchemeHandler(), forURLScheme: PetResources.scheme)
        config.websiteDataStore = .nonPersistent()
        config.userContentController.add(PetMessageProxy { [weak self] body in self?.handle(body) }, name: "pet")
        let web = WKWebView(frame: NSRect(origin: .zero, size: size), configuration: config)
        web.setValue(false, forKey: "drawsBackground")
        web.underPageBackgroundColor = .clear
        web.navigationDelegate = self
        web.autoresizingMask = [.width, .height]

        let input = PetInputView(frame: NSRect(origin: .zero, size: size))
        input.autoresizingMask = [.width, .height]
        input.onMove = { [weak self] p in self?.sendPointer("move", p) }
        input.onLeave = { [weak self] in self?.sendPointer("leave", nil) }
        input.onClick = { [weak self] p in self?.sendPointer("click", p) }
        input.onDoubleClick = { [weak self] p in self?.sendPointer("dblclick", p) }
        input.onContext = { [weak self] event in self?.showMenu(event) }
        input.onDragBegan = { [weak self] in
            self?.dragging = true
            self?.panel?.ignoresMouseEvents = false
            self?.send(["type": "drag", "phase": "start"])
        }
        input.onDragEnded = { [weak self] in
            self?.dragging = false
            self?.send(["type": "drag", "phase": "end"])
            self?.keepOnScreen()
            if let origin = self?.panel?.frame.origin { self?.prefs.origin = origin }
        }

        let container = NSView(frame: NSRect(origin: .zero, size: size))
        container.addSubview(web)
        container.addSubview(input)
        panel.contentView = container
        self.panel = panel
        self.web = web
        self.input = input
        place(panel)
        panel.orderFrontRegardless()
        installMonitors()
        NotificationCenter.default.addObserver(forName: NSWindow.didChangeOcclusionStateNotification, object: panel, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.occlusionChanged() }
        }
    }

    private func place(_ panel: PetPanel) {
        let size = panel.frame.size
        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let fallback = CGPoint(x: screen.maxX - size.width - 24, y: screen.minY + 8)
        panel.setFrameOrigin(prefs.origin ?? fallback)
        keepOnScreen()
    }

    /// Keeps the window reachable after a display change or a drag past the edge.
    private func keepOnScreen() {
        guard let panel else { return }
        let frame = panel.frame
        let screens = NSScreen.screens.map(\.visibleFrame)
        guard let target = screens.max(by: { $0.intersection(frame).area < $1.intersection(frame).area }) ?? NSScreen.main?.visibleFrame else { return }
        var origin = frame.origin
        origin.x = min(max(origin.x, target.minX - frame.width * 0.3), target.maxX - frame.width * 0.7)
        origin.y = min(max(origin.y, target.minY - 20), target.maxY - 60)
        if origin != frame.origin { panel.setFrameOrigin(origin) }
    }

    private func resizeWindow() {
        guard let panel else { return }
        let size = windowSize()
        let old = panel.frame
        panel.setFrame(NSRect(x: old.midX - size.width / 2, y: old.minY, width: size.width, height: size.height), display: true)
        keepOnScreen()
    }

    private func occlusionChanged() {
        guard let panel else { return }
        setVisible(panel.occlusionState.contains(.visible))
    }

    private func setVisible(_ on: Bool) {
        visible = on
        send(["type": "visibility", "visible": on])
    }

    // MARK: Page

    private var reduceMotion: Bool { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }

    private func schemeName() -> String {
        switch store.theme.forcedScheme {
        case .dark?: return "dark"
        case .light?: return "light"
        default: return NSApp.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? "dark" : "light"
        }
    }

    private func loadPage() {
        guard let web else { return }
        ready = false
        isActive = false
        if let url = PetPage.url(pack: prefs.packID, theme: store.theme.rawValue, scheme: schemeName(), scale: prefs.size.scale,
                                 hud: prefs.hud.rawValue, reduceMotion: reduceMotion, calm: prefs.calm) {
            web.load(URLRequest(url: url))
        }
    }

    func pushPrefs() {
        send(["type": "prefs", "prefs": [
            "hud": prefs.hud.rawValue, "scale": prefs.size.scale, "calm": prefs.calm, "chatter": !prefs.calm,
            "followCursor": prefs.followCursor, "reduceMotion": reduceMotion,
            "lowPower": ProcessInfo.processInfo.isLowPowerModeEnabled, "effects": !reduceMotion,
        ] as [String: Any]])
    }

    private func pushTheme() {
        send(["type": "theme", "id": store.theme.rawValue, "scheme": schemeName()])
    }

    private func send(_ message: [String: Any]) {
        guard let web, ready || message["type"] as? String == "visibility",
              let data = try? JSONSerialization.data(withJSONObject: message),
              let json = String(data: data, encoding: .utf8) else { return }
        web.evaluateJavaScript("window.AgentPet && window.AgentPet.receive(\(json))", completionHandler: nil)
    }

    private func sendPointer(_ event: String, _ point: CGPoint?) {
        var message: [String: Any] = ["type": "pointer", "ev": event]
        if let point { message["x"] = point.x; message["y"] = point.y }
        send(message)
    }

    // MARK: Frames

    private static let feedID = "desktop"

    /// The backend polling is shared with the panel's 桌宠 tab (see `PetFeed`); this window only listens.
    private func subscribeToFeed() {
        PetFeed.shared.subscribe(Self.feedID, isVisible: { [weak self] in
            guard let self, self.visible else { return false }
            return self.panel?.occlusionState.contains(.visible) ?? false
        }, onFrame: { [weak self] frame in self?.deliver(frame) })
    }

    private func deliver(_ frame: [String: Any]) {
        let fresh = PetFrameFilter.fresh(frame, shown: Set(shown.keys))
        lastState = frame["state"] as? String ?? ""
        if ready { send(["type": "frame", "frame": fresh]) } else { pending = fresh }
    }

    /// What the page shows when the backend cannot be reached: not "empty quota", just "disconnected".
    static func offlineFrame(now: Date = Date()) -> [String: Any] {
        ["schema_version": 1, "generated_at": now.timeIntervalSince1970, "state": "offline", "mood": "confused", "intensity": 1.0,
         "energy": ["known": false, "stale": false, "tone": "unknown"] as [String: Any], "meters": [Any](),
         "activity": ["known": false, "running": 0, "apps": [Any]()] as [String: Any], "focus": ["active": false] as [String: Any],
         "reminders": [Any](), "reasons": ["backend=unreachable"]]
    }

    private func markShown(_ id: String) {
        let now = Date().timeIntervalSince1970
        shown[id] = now
        shown = shown.filter { now - $0.value < 90 * 86400 }
        if shown.count > 2000 {
            // Bounded: forget the oldest rather than grow without limit.
            let keep = shown.sorted { $0.value > $1.value }.prefix(1500)
            shown = Dictionary(uniqueKeysWithValues: keep.map { ($0.key, $0.value) })
        }
        UserDefaults.standard.set(shown, forKey: "petShown")
    }

    // MARK: Messages from the page

    func handle(_ body: Any) {
        guard let message = PetMessage.parse(body) else { return }
        switch message {
        case .ready(_, let problem):
            ready = true
            isActive = true
            if let problem { NSLog("AgentMeterBar pet page: %@", problem) }
            pushPrefs()
            pushTheme()
            if let frame = pending { pending = nil; deliver(frame) }
            if let demo {
                deliver(Self.demoFrame(state: demo.state))
                DispatchQueue.main.asyncAfter(deadline: .now() + 4) { [weak self] in MainActor.assumeIsolated { self?.finishDemo() } }
            } else {
                PetFeed.shared.refreshNow()
            }
        case .rects(let rects, _):
            input?.hitRects = rects.map(\.rect)
        case .bubbleShown(let id):
            markShown(id)
        case .action(let action):
            run(action)
        case .hudClick:
            openPanel(tab: "accounts")
        case .refreshRequest:
            store.refresh()
        case .petClick:
            break
        case .error(let text):
            NSLog("AgentMeterBar pet page error: %@", text)
        }
    }

    // MARK: Demo mode (no backend, no Keychain)

    /// `AgentMeterBar --pet-demo <state> <out.png> -petPack bot -petEnabled YES`: opens the real pet window with a
    /// synthetic frame, checks that the page reported its hit regions, writes a transparent PNG and quits.
    func runDemo(state: String, outPath: String) {
        demo = (state, outPath)
        start()
    }

    static func demoFrame(state: String, now: Date = Date()) -> [String: Any] {
        let moods = ["working": "determined", "busy": "worried", "tired": "worried", "alarm": "worried", "exhausted": "sad",
                     "sleeping": "sleepy", "alert": "surprised", "excited": "excited", "confused": "confused", "offline": "confused",
                     "painting": "happy", "waiting": "happy", "focus": "determined"]
        var remaining: Double? = 82
        var tone = "ok"
        switch state {
        case "alarm": remaining = 4; tone = "critical"
        case "tired": remaining = 15; tone = "low"
        case "exhausted": remaining = 0; tone = "empty"
        case "offline", "confused": remaining = nil; tone = "unknown"
        default: break
        }
        let t = now.timeIntervalSince1970
        var energy: [String: Any] = ["known": remaining != nil, "tone": tone, "stale": false, "drives_state": true, "scope": "auto"]
        var meters: [[String: Any]] = []
        if let remaining {
            energy["remaining"] = remaining
            energy["label"] = "Codex · 5 小时"
            energy["resets_at"] = t + 9060
            meters = [["id": "codex:primary", "source": "codex", "name": "Codex", "window": "5 小时", "remaining": remaining, "tone": tone, "resets_at": t + 9060, "stale": false],
                      ["id": "claude:limit7d", "source": "claude", "name": "Claude", "window": "7 天", "remaining": 64.0, "tone": "ok", "resets_at": t + 4 * 86400, "stale": false]]
        }
        let running = state == "busy" ? 3 : (state == "working" ? 1 : 0)
        let apps: [[String: Any]] = running > 0 ? [["app": "codex", "label": "Codex", "count": running, "project": "NEW-agent 统计"]] : []
        var reminders: [[String: Any]] = []
        if state == "alert" {
            reminders = [["id": "demo-card", "kind": "reset_card", "text": "Codex 重置卡即将到期：2 张将于明天 16:53 到期", "tone": "warn", "priority": 70,
                          "action": ["kind": "open_panel", "tab": "accounts"] as [String: Any]]]
        }
        return ["schema_version": 1, "generated_at": t, "state": state, "mood": moods[state] ?? "happy", "intensity": 0.7,
                "energy": energy, "meters": meters, "activity": ["known": true, "running": running, "apps": apps] as [String: Any],
                "focus": ["active": state == "focus"] as [String: Any], "reminders": reminders, "reasons": ["demo"]]
    }

    private func finishDemo() {
        guard let demo, let web, let panel, let input else { exit(3) }
        let reported = input.hitRects
        let corner = input.isInteractive(CGPoint(x: 1, y: 1), slop: 0)
        let center = reported.first.map { input.isInteractive(CGPoint(x: $0.midX, y: $0.midY), slop: 0) } ?? false
        web.takeSnapshot(with: nil) { image, error in
            MainActor.assumeIsolated {
                guard let tiff = image?.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
                      let png = rep.representation(using: .png, properties: [:]) else {
                    FileHandle.standardError.write(Data("snapshot failed: \(String(describing: error))\n".utf8))
                    exit(4)
                }
                try? png.write(to: URL(fileURLWithPath: demo.out))
                print("pet-demo state=\(demo.state) pack=\(self.prefs.packID) ready=\(self.ready) visible=\(panel.isVisible) "
                      + "level=\(panel.level.rawValue) canBecomeKey=\(panel.canBecomeKey) hitRects=\(reported.count) "
                      + "cornerInteractive=\(corner) centerInteractive=\(center) size=\(Int(panel.frame.width))x\(Int(panel.frame.height))")
                exit(reported.isEmpty || corner || !center ? 5 : 0)
            }
        }
    }

    private func run(_ action: PetAction) {
        switch action {
        case .openPanel(let tab): openPanel(tab: tab)
        }
    }

    func openPanel(tab: String?) {
        if let tab { UserDefaults.standard.set(tab, forKey: "panelTab") }
        StatusBarController.shared.showPanel()
    }

    /// The folder where self-made packs go (created on demand); the menu opens it in Finder.
    func openUserFolder() {
        let dir = PetResources.userPacksDirectory
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        NSWorkspace.shared.open(dir)
    }

    private func emit(_ payload: [String: Any]) { PetFeed.shared.emit(payload) }

    // MARK: Click-through and cursor following

    private func installMonitors() {
        guard monitors.isEmpty else { return }
        let handler: (NSEvent) -> Void = { [weak self] _ in
            if Thread.isMainThread {
                MainActor.assumeIsolated { self?.pointerMoved() }
            } else {
                DispatchQueue.main.async { MainActor.assumeIsolated { self?.pointerMoved() } }
            }
        }
        if let global = NSEvent.addGlobalMonitorForEvents(matching: [.mouseMoved], handler: handler) { monitors.append(global) }
        if let local = NSEvent.addLocalMonitorForEvents(matching: [.mouseMoved], handler: { event in handler(event); return event }) {
            monitors.append(local)
        }
    }

    private func removeMonitors() {
        monitors.forEach { NSEvent.removeMonitor($0) }
        monitors = []
    }

    /// Transparent margins must not eat clicks meant for the app underneath: the window ignores the mouse
    /// unless the pointer is over something the page reported as interactive.
    private func pointerMoved() {
        guard let panel, let input, panel.isVisible, !dragging else { return }
        let point = input.convert(panel.convertPoint(fromScreen: NSEvent.mouseLocation), from: nil)
        let inside = input.isInteractive(point)
        if panel.ignoresMouseEvents == inside { panel.ignoresMouseEvents = !inside }
        if prefs.followCursor, visible, Date().timeIntervalSince(lastCursorSent) > 0.07 {
            // Eyes only follow a cursor that is reasonably close; far away they settle once and stop costing anything.
            let near = hypot(point.x - input.bounds.midX, point.y - input.bounds.midY) < 900
            if near || cursorWasNear {
                lastCursorSent = Date()
                send(near ? ["type": "cursor", "x": point.x, "y": point.y] : ["type": "cursor"])
            }
            cursorWasNear = near
        }
    }

    // MARK: Context menu

    private func showMenu(_ event: NSEvent) {
        guard let input else { return }
        let menu = NSMenu()
        menu.addItem(ClosureMenuItem("立即刷新") { [weak self] in self?.store.refresh() })

        let panelMenu = NSMenu()
        for (title, tab) in [("账户额度", "accounts"), ("应用与会话", "apps"), ("重置预测", "forecast"), ("本机消耗", "usage"), ("桌宠", "pet")] {
            panelMenu.addItem(ClosureMenuItem(title) { [weak self] in self?.openPanel(tab: tab) })
        }
        let panelItem = NSMenuItem(title: "打开面板", action: nil, keyEquivalent: "")
        panelItem.submenu = panelMenu
        menu.addItem(panelItem)
        menu.addItem(ClosureMenuItem("分享用量报告…") { ReportWindow.show() })
        menu.addItem(.separator())

        let focusMenu = NSMenu()
        for minutes in [25, 50] {
            focusMenu.addItem(ClosureMenuItem("\(minutes) 分钟") { [weak self] in self?.emit(["kind": "focus_start", "minutes": minutes]) })
        }
        focusMenu.addItem(ClosureMenuItem("结束专注") { [weak self] in self?.emit(["kind": "focus_stop"]) })
        let focusItem = NSMenuItem(title: "专注计时", action: nil, keyEquivalent: "")
        focusItem.submenu = focusMenu
        menu.addItem(focusItem)
        menu.addItem(.separator())

        let packMenu = NSMenu()
        for pack in packs {
            packMenu.addItem(ClosureMenuItem(pack.name + (pack.builtin ? "" : "（自制）"), checked: pack.id == prefs.packID) { [weak self] in self?.prefs.packID = pack.id })
        }
        let packItem = NSMenuItem(title: "形象", action: nil, keyEquivalent: "")
        packItem.submenu = packMenu
        menu.addItem(packItem)

        let sizeMenu = NSMenu()
        for size in PetSize.allCases {
            sizeMenu.addItem(ClosureMenuItem(size.label, checked: size == prefs.size) { [weak self] in self?.prefs.size = size })
        }
        let sizeItem = NSMenuItem(title: "大小", action: nil, keyEquivalent: "")
        sizeItem.submenu = sizeMenu
        menu.addItem(sizeItem)

        let hudMenu = NSMenu()
        for hud in PetHUD.allCases {
            hudMenu.addItem(ClosureMenuItem(hud.label, checked: hud == prefs.hud) { [weak self] in self?.prefs.hud = hud })
        }
        let hudItem = NSMenuItem(title: "额度显示", action: nil, keyEquivalent: "")
        hudItem.submenu = hudMenu
        menu.addItem(hudItem)

        menu.addItem(ClosureMenuItem("安静模式", checked: prefs.calm) { [weak self] in self?.prefs.calm.toggle() })
        menu.addItem(.separator())
        menu.addItem(ClosureMenuItem("隐藏桌宠") { [weak self] in self?.prefs.enabled = false })
        NSMenu.popUpContextMenu(menu, with: event, for: input)
    }

    // MARK: WKNavigationDelegate

    nonisolated func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                             decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
        let scheme = navigationAction.request.url?.scheme
        let allowed = scheme == PetResources.scheme || scheme == "about"
        MainActor.assumeIsolated { decisionHandler(allowed ? .allow : .cancel) }
    }

    nonisolated func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        MainActor.assumeIsolated { [weak self] in
            self?.ready = false
            self?.loadPage()
        }
    }
}

private extension NSRect {
    var area: CGFloat { isNull || isEmpty ? 0 : width * height }
}
