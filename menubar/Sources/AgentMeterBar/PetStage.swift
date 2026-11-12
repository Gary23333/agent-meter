import AppKit
import Observation
import SwiftUI
import WebKit

/// The stage's web view: it never takes keyboard focus, hands scrolling to the panel's scroll view (the stage itself
/// never scrolls) and has no context menu of its own.
final class PetWebView: WKWebView {
    var onWindowChange: ((NSWindow?) -> Void)?
    var onAppearanceChange: (() -> Void)?

    override var acceptsFirstResponder: Bool { false }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override func scrollWheel(with event: NSEvent) { nextResponder?.scrollWheel(with: event) }
    override func willOpenMenu(_ menu: NSMenu, with event: NSEvent) { menu.removeAllItems() }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        onWindowChange?(window)
    }

    override func viewDidChangeEffectiveAppearance() {
        super.viewDidChangeEffectiveAppearance()
        onAppearanceChange?()
    }
}

/// The live pet inside the panel's 桌宠 tab. One page for the whole app run: the web view is created once and moved
/// into whichever view shows it, so switching tabs does not rebuild the 3D scene. It listens to the shared
/// `PetFeed` while the tab is open; the user can try any state or reaction on it without touching the real pet,
/// the backend or the desktop window.
@MainActor @Observable
final class PetStageHost: NSObject, WKNavigationDelegate {
    static let shared = PetStageHost()

    /// The state or reaction being tried out instead of the live one (nil: the stage shows the real thing).
    private(set) var previewID: String?
    private(set) var ready = false
    /// Why the page could not start, if it could not.
    private(set) var problem: String?

    /// How long a state stays on stage before the real one returns.
    static let previewSeconds: TimeInterval = 8
    /// How long after the tab is left the page (a web content process and a GL context) is kept around.
    static let idleSeconds: TimeInterval = 60

    @ObservationIgnored private let prefs = PetPrefs.shared
    @ObservationIgnored private let store = UsageStore.shared
    @ObservationIgnored private var storedWeb: PetWebView?
    @ObservationIgnored private var attached = false
    @ObservationIgnored private var pageVisible = false
    @ObservationIgnored private var loadedKey = ""
    @ObservationIgnored private var liveFrame: [String: Any]?
    @ObservationIgnored private var shownFrame: [String: Any]?
    @ObservationIgnored private var restoreTimer: Timer?
    @ObservationIgnored private var reactionCounter = 0
    @ObservationIgnored private var tracking = false
    @ObservationIgnored private var occlusionObserver: NSObjectProtocol?
    @ObservationIgnored private var teardownTimer: Timer?
    @ObservationIgnored private var greetOnReady = false

    private static let feedID = "stage"

    var web: PetWebView {
        if let storedWeb { return storedWeb }
        let config = WKWebViewConfiguration()
        config.setURLSchemeHandler(PetSchemeHandler(), forURLScheme: PetResources.scheme)
        config.websiteDataStore = .nonPersistent()
        config.userContentController.add(PetMessageProxy { [weak self] body in self?.handle(body) }, name: "pet")
        let view = PetWebView(frame: NSRect(x: 0, y: 0, width: 364, height: 260), configuration: config)
        view.setValue(false, forKey: "drawsBackground")
        view.underPageBackgroundColor = .clear
        view.navigationDelegate = self
        view.onWindowChange = { [weak self] window in self?.windowChanged(window) }
        view.onAppearanceChange = { [weak self] in self?.pushTheme() }
        storedWeb = view
        return view
    }

    // MARK: Lifecycle

    /// The tab appeared: start listening and make sure the right pack is loaded.
    func attach() {
        attached = true
        teardownTimer?.invalidate()
        teardownTimer = nil
        _ = web
        track()
        PetFeed.shared.subscribe(Self.feedID, isVisible: { [weak self] in self?.pageVisible ?? false },
                                 onFrame: { [weak self] frame in self?.receive(frame) })
        sync()
        updateVisibility()
    }

    /// The tab went away: stop listening, which lets the feed rest if nothing else shows the pet.
    func detach() {
        attached = false
        restoreTimer?.invalidate()
        restoreTimer = nil
        previewID = nil
        PetFeed.shared.unsubscribe(Self.feedID)
        updateVisibility()
        teardownTimer?.invalidate()
        teardownTimer = Timer.scheduledTimer(withTimeInterval: Self.idleSeconds, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated { self?.teardown() }
        }
    }

    /// Frees the page after the tab has been left for a while; the next visit builds it again.
    private func teardown() {
        guard !attached, let view = storedWeb else { return }
        view.stopLoading()
        view.configuration.userContentController.removeScriptMessageHandler(forName: "pet")
        view.removeFromSuperview()
        storedWeb = nil
        ready = false
        loadedKey = ""
        pageVisible = false
    }

    private func track() {
        guard !tracking else { return }
        tracking = true
        observeChanges()
    }

    private func observeChanges() {
        withObservationTracking {
            _ = (prefs.packID, prefs.calm, prefs.followCursor, store.theme)
        } onChange: { [weak self] in
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    guard let self else { return }
                    self.observeChanges()
                    if self.attached { self.sync() }
                }
            }
        }
    }

    /// Reloads the page when the pack changed; anything else is a message to the running page.
    private func sync() {
        let key = prefs.packID + "|" + (reduceMotion ? "r" : "-")
        if key != loadedKey || web.url == nil {
            // A different form (not the first load, not a reload) greets with a wave once it is on stage.
            greetOnReady = !loadedKey.isEmpty && loadedKey.split(separator: "|").first != key.split(separator: "|").first
            loadedKey = key
            load()
        } else {
            pushPrefs()
            pushTheme()
        }
    }

    private var reduceMotion: Bool { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }

    private func schemeName() -> String {
        switch store.theme.forcedScheme {
        case .dark?: return "dark"
        case .light?: return "light"
        default: return web.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? "dark" : "light"
        }
    }

    private func load() {
        ready = false
        problem = nil
        guard PetResources.root() != nil else {
            problem = "找不到桌宠资源（pets/ 文件夹）"
            return
        }
        if let url = PetPage.url(pack: prefs.packID, theme: store.theme.rawValue, scheme: schemeName(), scale: 1, hud: "off",
                                 reduceMotion: reduceMotion, calm: prefs.calm, mode: .embed) {
            web.load(URLRequest(url: url))
        }
    }

    // MARK: Visibility

    private func windowChanged(_ window: NSWindow?) {
        if let occlusionObserver { NotificationCenter.default.removeObserver(occlusionObserver) }
        occlusionObserver = nil
        if let window {
            occlusionObserver = NotificationCenter.default.addObserver(forName: NSWindow.didChangeOcclusionStateNotification, object: window, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.updateVisibility() }
            }
        }
        updateVisibility()
        pushTheme()
    }

    private func updateVisibility() {
        let visible = attached && (storedWeb?.window?.occlusionState.contains(.visible) ?? false)
        guard visible != pageVisible else { return }
        pageVisible = visible
        send(["type": "visibility", "visible": visible])
    }

    // MARK: Talking to the page

    private func send(_ message: [String: Any]) {
        guard let storedWeb, ready || message["type"] as? String == "visibility",
              let data = try? JSONSerialization.data(withJSONObject: message),
              let json = String(data: data, encoding: .utf8) else { return }
        storedWeb.evaluateJavaScript("window.AgentPet && window.AgentPet.receive(\(json))", completionHandler: nil)
    }

    private func pushPrefs() {
        send(["type": "prefs", "prefs": [
            "hud": "off", "scale": 1.0, "calm": prefs.calm, "chatter": !prefs.calm, "followCursor": prefs.followCursor,
            "reduceMotion": reduceMotion, "lowPower": ProcessInfo.processInfo.isLowPowerModeEnabled, "effects": !reduceMotion,
        ] as [String: Any]])
    }

    private func pushTheme() {
        send(["type": "theme", "id": store.theme.rawValue, "scheme": schemeName()])
    }

    /// What the stage is given: reminders stay out. The tab lists them in words, and the desktop pet (or the
    /// system notification) is the one that announces them, so a reminder is never said twice.
    nonisolated static func stageFrame(_ frame: [String: Any]) -> [String: Any] {
        var out = frame
        out["reminders"] = [Any]()
        return out
    }

    private func show(_ frame: [String: Any]) {
        shownFrame = frame
        send(["type": "frame", "frame": Self.stageFrame(frame)])
    }

    /// A frame from the feed. While a state is being tried out the real one waits.
    private func receive(_ frame: [String: Any]) {
        liveFrame = frame
        guard previewID == nil else { return }
        show(frame)
    }

    // MARK: Trying things out

    /// Shows a state the pet may not be in right now, using the same canned numbers as the demo window.
    func previewState(_ id: String) {
        guard PetCatalog.states.contains(where: { $0.id == id }) else { return }
        begin(id)
        var frame = PetController.demoFrame(state: id)
        frame["reasons"] = ["preview"]
        show(frame)
    }

    /// Plays a short reaction on top of whatever the stage is showing.
    func previewReaction(_ id: String) {
        guard PetCatalog.reactions.contains(where: { $0.id == id }) else { return }
        reactionCounter += 1
        var frame = shownFrame ?? liveFrame ?? PetController.demoFrame(state: "idle")
        let now = Date().timeIntervalSince1970
        frame["generated_at"] = now
        frame["reaction"] = ["id": id, "key": "tab-\(reactionCounter)", "until": now + 6, "reason": "preview"] as [String: Any]
        show(frame)
    }

    /// Back to the real state.
    func endPreview() {
        restoreTimer?.invalidate()
        restoreTimer = nil
        guard previewID != nil else { return }
        previewID = nil
        show(liveFrame ?? PetController.demoFrame(state: "idle"))
    }

    private func begin(_ id: String) {
        previewID = id
        restoreTimer?.invalidate()
        restoreTimer = Timer.scheduledTimer(withTimeInterval: Self.previewSeconds, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated { self?.endPreview() }
        }
    }

    /// The stage as a picture, for screenshots in a window that is not on screen (see `PreviewRenderer`): the page
    /// plays a little animation by hand, since a hidden window gets no animation frames, and returns the pet.
    func capture(_ completion: @escaping (NSImage?) -> Void, effects: Bool = true) {
        guard ready, let storedWeb else { completion(nil); return }
        storedWeb.evaluateJavaScript("window.__pet ? window.__pet.stage.capture({ settle: 0.8, fx: \(effects ? "true" : "false") }) : ''") { result, _ in
            MainActor.assumeIsolated { completion(PetThumbnails.image(fromDataURL: result as? String ?? "")) }
        }
    }

    // MARK: Messages from the page

    private func handle(_ body: Any) {
        guard let message = PetMessage.parse(body) else { return }
        switch message {
        case .ready(_, let reported):
            ready = true
            problem = reported
            pushPrefs()
            pushTheme()
            send(["type": "visibility", "visible": pageVisible])
            if let frame = shownFrame ?? liveFrame { show(frame) }
            if greetOnReady {
                greetOnReady = false
                previewReaction("wave")
            }
            PetFeed.shared.refreshNow()
        case .action(.openPanel(let tab)):
            if let tab { UserDefaults.standard.set(tab, forKey: "panelTab") }
        case .sessionClick(let app):
            if let problem = AppLauncher.openApp(forApp: app, in: store.snapshot) {
                send(["type": "say", "bubble": ["text": problem, "tone": "warn", "ttl": 10, "priority": 80] as [String: Any]])
            }
        case .refreshRequest:
            store.refresh()
        case .error(let text):
            NSLog("AgentMeterBar pet stage page error: %@", text)
        case .rects, .bubbleShown, .hudClick, .petClick:
            break
        }
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
            if self?.attached == true { self?.load() }
        }
    }
}

/// Puts the shared stage web view into the SwiftUI hierarchy.
struct PetStageView: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let container = NSView()
        let web = PetStageHost.shared.web
        web.removeFromSuperview()
        web.frame = container.bounds
        web.autoresizingMask = [.width, .height]
        container.addSubview(web)
        return container
    }

    func updateNSView(_ nsView: NSView, context: Context) {}

    static func dismantleNSView(_ nsView: NSView, coordinator: ()) {
        nsView.subviews.forEach { $0.removeFromSuperview() }
    }
}
