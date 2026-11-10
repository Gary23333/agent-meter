import AppKit
import SwiftUI

@main
struct AgentMeterBarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    // The status item and popover are AppKit-managed (see StatusBarController);
    // a never-inserted MenuBarExtra satisfies App without opening any window.
    var body: some Scene {
        MenuBarExtra("Agent 用量", isInserted: .constant(false)) { EmptyView() }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var sigterm: DispatchSourceSignal?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        // `kill`/logout send SIGTERM, which skips applicationWillTerminate;
        // route it through a normal quit so the owned backend is stopped.
        signal(SIGTERM, SIG_IGN)
        let source = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
        source.setEventHandler { NSApp.terminate(nil) }
        source.resume()
        sigterm = source

        let args = CommandLine.arguments
        // One instance only: a second copy would fight over the backend.
        if !args.contains("--preview"), !args.contains("--pet-sheet"), !args.contains("--pet-demo"), let id = Bundle.main.bundleIdentifier,
           NSRunningApplication.runningApplications(withBundleIdentifier: id)
               .contains(where: { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier }) {
            NSApp.terminate(nil)
            return
        }
        // `--pet-sheet <pack-id[,id...]> <out.png> [query]`: contact sheet of a pet pack, rendered headlessly.
        if let i = args.firstIndex(of: "--pet-sheet"), args.count > i + 2 {
            MainActor.assumeIsolated {
                PetSheetRunner.run(pack: args[i + 1], outPath: args[i + 2], arguments: args.count > i + 3 ? args[i + 3] : "")
            }
            return
        }
        // `--pet-demo <state> <out.png> -petPack <id> -petEnabled YES`: the real pet window driven by a synthetic
        // frame; touches neither the backend nor the Keychain.
        if let i = args.firstIndex(of: "--pet-demo"), args.count > i + 2 {
            MainActor.assumeIsolated { PetController.shared.runDemo(state: args[i + 1], outPath: args[i + 2]) }
            return
        }
        if let i = args.firstIndex(of: "--preview"), args.count > i + 2 {
            MainActor.assumeIsolated { PreviewRenderer.run(snapshot: args[i + 1], outDir: args[i + 2]) }
            return
        }
        MainActor.assumeIsolated {
            StatusBarController.shared.install(store: UsageStore.shared)
            Notifier.shared.setup()
            PetController.shared.start()
            // `--panel-window`: the panel in a normal window (development aid; see DevPanelWindow).
            if args.contains("--panel-window") { DevPanelWindow.show(selfTest: args.contains("--selftest")) }
        }
        Task { @MainActor in
            await UsageStore.shared.bootstrap()
            // Debug aid for measuring the open panel (e.g. its animation cost).
            if ProcessInfo.processInfo.environment["AGENT_METER_OPEN_PANEL"] == "1" { StatusBarController.shared.showPanel() }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        MainActor.assumeIsolated { UsageStore.shared.shutdown() }
    }
}
