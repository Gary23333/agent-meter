import AppKit
import Observation
import SwiftUI
import WebKit

/// `--panel-window`: the panel in an ordinary window instead of the menu bar popover. A development aid for a build
/// whose status item is hidden or crowded out, and for screenshots of the real thing; it is the same view with the
/// same store, so what it shows is what the popover shows. With `--selftest` it also drives the window with real
/// (in-process) events and exits with the result; see `PanelSelfTest`.
@MainActor
enum DevPanelWindow {
    private static var window: NSWindow?

    static func show(selfTest: Bool = false) {
        let store = UsageStore.shared
        let controller = NSHostingController(rootView: PanelView().environment(store))
        controller.sizingOptions = .preferredContentSize
        let window = NSWindow(contentViewController: controller)
        window.title = "Agent 用量 · 开发窗口"
        window.styleMask = [.titled, .closable, .miniaturizable]
        window.isReleasedWhenClosed = false
        // Top right, where the popover would open: out of the way of whatever else is on screen.
        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        window.setFrameTopLeftPoint(NSPoint(x: screen.maxX - 420 - 24, y: screen.maxY - 24))   // the panel is 420 wide; the window has no size yet
        Self.window = window
        track(store)
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()   // an accessory app is not always allowed to activate; this does not need it
        NSApp.activate()
        print("panel-window id=\(window.windowNumber)")
        fflush(stdout)
        if selfTest { PanelSelfTest.run(in: window) }
    }

    /// Neon, titanium and prism are always dark, like the popover frame.
    private static func track(_ store: UsageStore) {
        withObservationTracking {
            window?.appearance = store.theme.forcedScheme == .dark ? NSAppearance(named: .darkAqua) : nil
        } onChange: {
            DispatchQueue.main.async { MainActor.assumeIsolated { track(store) } }
        }
    }
}

/// `--panel-window --selftest`: the interactions that only a real window can prove. Real `NSEvent`s are sent into the
/// panel window (no Accessibility permission is needed for events that never leave the process), and the result is
/// read back from the views. It prints PASS/FAIL lines and exits 0 only if everything held.
@MainActor
enum PanelSelfTest {
    private static var failures = 0

    private static func check(_ ok: Bool, _ what: String) {
        print((ok ? "PASS  " : "FAIL  ") + what)
        if !ok { failures += 1 }
    }

    private static func wait(_ seconds: Double) async { try? await Task.sleep(for: .seconds(seconds)) }

    private static func waitUntil(_ seconds: Double, _ condition: @MainActor () -> Bool) async -> Bool {
        let deadline = Date().addingTimeInterval(seconds)
        while Date() < deadline {
            if condition() { return true }
            await wait(0.1)
        }
        return condition()
    }

    private static func scrollView(in view: NSView?) -> NSScrollView? {
        guard let view else { return nil }
        if let scroll = view as? NSScrollView, let document = scroll.documentView, document.frame.height > scroll.contentSize.height + 1 { return scroll }
        return view.subviews.lazy.compactMap { scrollView(in: $0) }.first
    }

    private static func js(_ web: WKWebView, _ script: String) async -> String {
        await withCheckedContinuation { continuation in
            web.evaluateJavaScript(script) { result, _ in continuation.resume(returning: (result as? String) ?? "") }
        }
    }

    static func run(in window: NSWindow) {
        Task { @MainActor in
            UserDefaults.standard.set("pet", forKey: "panelTab")
            let host = PetStageHost.shared
            check(await waitUntil(25) { host.ready }, "the stage page loads and reports ready")
            PetFeed.shared.inject(PetController.demoFrame(state: "idle"))
            await wait(1.0)

            // 1. The mouse wheel over the stage must scroll the panel (the page itself never scrolls).
            let web = host.web
            check(web.window === window, "the stage web view lives in the panel window")
            let scroll = scrollView(in: window.contentView)
            check(scroll != nil, "the panel's content is a scroll view taller than its window")
            if let scroll {
                let before = scroll.contentView.bounds.origin.y
                if let cg = CGEvent(scrollWheelEvent2Source: nil, units: .pixel, wheelCount: 1, wheel1: -160, wheel2: 0, wheel3: 0),
                   let event = NSEvent(cgEvent: cg) {
                    web.scrollWheel(with: event)
                }
                await wait(0.6)
                let after = scroll.contentView.bounds.origin.y
                check(abs(after - before) > 20, "a wheel event on the stage scrolls the panel (offset \(Int(before)) -> \(Int(after)))")
                scroll.contentView.scroll(to: NSPoint(x: 0, y: before))
                scroll.reflectScrolledClipView(scroll.contentView)
            }

            // 2. A click on the pet pokes it: the page answers with a speech bubble that says what it knows.
            let geometry = await js(web, "(() => { const s = window.__pet.stage, b = s.renderer.bounds(); return JSON.stringify([s.petRect.x + b.x + b.w / 2, s.petRect.y + b.y + b.h / 2]); })()")
            if let data = geometry.data(using: .utf8), let center = try? JSONSerialization.jsonObject(with: data) as? [Double], center.count == 2 {
                let point = web.convert(NSPoint(x: center[0], y: center[1]), to: nil)
                @MainActor func mouse(_ type: NSEvent.EventType) -> NSEvent? {
                    NSEvent.mouseEvent(with: type, location: point, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                                       windowNumber: window.windowNumber, context: nil, eventNumber: 0, clickCount: 1, pressure: 1)
                }
                if let down = mouse(.leftMouseDown), let up = mouse(.leftMouseUp) {
                    window.sendEvent(down)
                    await wait(0.08)
                    window.sendEvent(up)
                }
                var text = ""
                for _ in 0..<20 where text.isEmpty {
                    await wait(0.2)
                    text = await js(web, "(() => { const b = window.__pet.stage.bubble.current; return b ? b.text : ''; })()")
                }
                check(!text.isEmpty, "clicking the pet makes it speak: \u{300C}\(text)\u{300D}")
            } else {
                check(false, "the pet's position could not be read from the page")
            }

            // The gallery gets a picture for every pack, drawn by the pet's own runtime in a hidden window.
            let thumbnails = PetThumbnails.shared
            let packCount = PetResources.allPacks().count
            check(await waitUntil(30) { thumbnails.images.count == packCount && packCount > 0 },
                  "the gallery draws a thumbnail for every pack (\(thumbnails.images.count)/\(packCount), failed: \(thumbnails.failed.count))")

            // 3. Trying a state changes the stage only; the real frame comes back afterwards.
            host.previewState("alarm")
            check(host.previewID == "alarm", "trying a state shows it on the stage")
            host.endPreview()
            check(host.previewID == nil, "ending the preview returns to the real state")

            // 4. Leaving the tab lets the feed rest; coming back resumes it.
            let before = PetFeed.shared.subscriberCount
            UserDefaults.standard.set("apps", forKey: "panelTab")
            check(await waitUntil(3) { PetFeed.shared.subscriberCount == before - 1 }, "leaving the pet tab stops its feed subscription")
            UserDefaults.standard.set("pet", forKey: "panelTab")
            check(await waitUntil(3) { PetFeed.shared.subscriberCount == before }, "coming back resumes it")

            print(failures == 0 ? "ALL PASSED" : "\(failures) FAILED")
            fflush(stdout)
            UsageStore.shared.shutdown()   // exit() skips applicationWillTerminate; stop the backend this run started
            exit(failures == 0 ? 0 : 1)
        }
    }
}
