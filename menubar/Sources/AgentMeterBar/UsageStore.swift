import Foundation
import Observation
import ServiceManagement
import SwiftUI

enum MenuBarMode: String, CaseIterable, Identifiable {
    case ticker, flip, tightest, todayTokens, iconOnly
    var id: String { rawValue }
    var label: String {
        switch self {
        case .ticker: return "滚动行情"
        case .flip: return "逐条翻动"
        case .tightest: return "最紧张的额度"
        case .todayTokens: return "今日 Token"
        case .iconOnly: return "仅图标"
        }
    }
}

enum TickerWidth: String, CaseIterable, Identifiable {
    case narrow, medium, wide
    var id: String { rawValue }
    var label: String {
        switch self {
        case .narrow: return "窄（160）"
        case .medium: return "中（220）"
        case .wide: return "宽（300）"
        }
    }
    var points: CGFloat {
        switch self {
        case .narrow: return 160
        case .medium: return 220
        case .wide: return 300
        }
    }
}

enum Phase: Equatable {
    case idle, starting, loading, refreshing
}

@MainActor @Observable
final class UsageStore {
    static let shared = UsageStore()

    var snapshot: Snapshot?
    var phase: Phase = .idle
    var errorMessage: String?
    var lastFetched: Date?
    var now = Date()
    var menuBarMode: MenuBarMode {
        didSet { UserDefaults.standard.set(menuBarMode.rawValue, forKey: "menuBarMode") }
    }
    var theme: PanelTheme {
        didSet { UserDefaults.standard.set(theme.rawValue, forKey: "panelTheme") }
    }
    var tickerWidth: TickerWidth {
        didSet { UserDefaults.standard.set(tickerWidth.rawValue, forKey: "tickerWidth") }
    }
    var notificationsEnabled: Bool {
        didSet { UserDefaults.standard.set(notificationsEnabled, forKey: "notificationsEnabled") }
    }
    /// Remaining-percent level that triggers a low-quota alert.
    var lowQuotaThreshold: Double {
        didSet { UserDefaults.standard.set(lowQuotaThreshold, forKey: "lowQuotaThreshold") }
    }
    /// Claude quota reading (Keychain / claude.ai login) can be switched off.
    var claudeEnabled: Bool {
        didSet {
            UserDefaults.standard.set(claudeEnabled, forKey: "claudeEnabled")
            Task { await pushPreferences(); await fetch(force: true) }
        }
    }
    var launchAtLogin: Bool = SMAppService.mainApp.status == .enabled

    @ObservationIgnored private let backend = BackendProcess()
    /// Read-only accessor for windows that talk to the backend directly.
    var backendClient: BackendClient? { client }
    @ObservationIgnored private var client: BackendClient?
    @ObservationIgnored private var loops: [Task<Void, Never>] = []
    @ObservationIgnored private var fetchTask: Task<Void, Never>?
    /// Ticker change arrows: last distinct value and its change, per item.
    @ObservationIgnored private var tickerBaseline: [String: Double] = [:]
    var tickerDelta: [String: Double] = [:]
    /// Website logins in memory, so re-pushing never touches the Keychain.
    @ObservationIgnored private var sessions: [String: [String: String]] = [:]

    /// Matches the backend cache TTL; panel opens reuse the cached snapshot.
    private let pollInterval: TimeInterval = 300

    private init() {
        let d = UserDefaults.standard
        menuBarMode = MenuBarMode(rawValue: d.string(forKey: "menuBarMode") ?? "") ?? .ticker
        tickerWidth = TickerWidth(rawValue: d.string(forKey: "tickerWidth") ?? "") ?? .medium
        theme = PanelTheme(rawValue: d.string(forKey: "panelTheme") ?? "") ?? .aurora
        notificationsEnabled = d.object(forKey: "notificationsEnabled") as? Bool ?? true
        claudeEnabled = d.object(forKey: "claudeEnabled") as? Bool ?? true
        lowQuotaThreshold = d.object(forKey: "lowQuotaThreshold") as? Double ?? 20
    }

    var projectDirectory: URL? { client?.project }
    var isBusy: Bool { phase != .idle }

    func bootstrap() async {
        guard client == nil else { return }
        guard let project = BackendProcess.projectDirectory() else {
            errorMessage = BackendError.projectNotFound.localizedDescription
            return
        }
        let client = BackendClient(project: project)
        self.client = client
        phase = .starting
        do {
            try await ensureBackend(client)
        } catch {
            phase = .idle
            errorMessage = error.localizedDescription
            NSLog("AgentMeterBar backend start: %@", String(describing: error))
            return
        }
        phase = .idle
        await pushPreferences()
        await fetch(force: false)
        startLoops()
        // Saved website logins load in the background; a Keychain prompt
        // (e.g. after a rebuild) then delays only those sources.
        let stored = await ConnectionManager.shared.storedSessions()
        if !stored.isEmpty {
            sessions = stored
            await pushSessions()
            await fetch(force: true)
        }
        await observeDreamina()
        loops.append(Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30 * 60))
                await self?.observeDreamina()
            }
        })
    }

    private func ensureBackend(_ client: BackendClient) async throws {
        if await client.healthy() { return }
        if await client.portInUse() {
            // Give a just-started external backend a moment before deciding.
            try? await Task.sleep(for: .seconds(1))
            if await client.healthy() { return }
            throw BackendError.unauthorized
        }
        try backend.start(project: client.project)
        for _ in 0..<40 {
            try? await Task.sleep(for: .milliseconds(250))
            if await client.healthy() { return }
            if !backend.isOwned { throw BackendError.startFailed }
        }
        throw BackendError.startFailed
    }

    private func startLoops() {
        loops.append(Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(20))
                self?.now = Date()
            }
        })
        loops.append(Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(self?.pollInterval ?? 300))
                await self?.fetch(force: false)
            }
        })
    }

    /// Called when the panel opens; only fetches when the data is getting old.
    func panelOpened() {
        now = Date()
        if let last = lastFetched, now.timeIntervalSince(last) < 120 { return }
        if client == nil { Task { await bootstrap() } } else { Task { await fetch(force: false) } }
    }

    func refresh() {
        Task {
            if client == nil || snapshot == nil && errorMessage != nil {
                client = nil
                errorMessage = nil
                await bootstrap()
            } else {
                await fetch(force: true)
                if (DreaminaMonitor.shared.lastRun.map { Date().timeIntervalSince($0) > 300 } ?? true) {
                    await observeDreamina()
                }
            }
        }
    }

    func fetch(force: Bool) async {
        guard let client, fetchTask == nil else { return }
        phase = force ? .refreshing : (snapshot == nil ? .loading : .refreshing)
        let task = Task { @MainActor in
            do {
                var result: Snapshot
                do { result = try await client.snapshot(force: force) }
                catch BackendError.unreachable {
                    // The backend went away (sleep, crash): bring it back once.
                    if await client.healthy() { throw BackendError.unreachable }
                    try await ensureBackend(client)
                    await pushPreferences()
                    await pushSessions()
                    result = try await client.snapshot(force: force)
                }
                snapshot = result
                updateTickerDeltas(result)
                lastFetched = Date()
                errorMessage = nil
                Notifier.shared.evaluate(result, store: self, now: Date())
            } catch {
                errorMessage = error.localizedDescription
                NSLog("AgentMeterBar fetch: %@", String(describing: error))
            }
            now = Date()
            phase = .idle
        }
        fetchTask = task
        await task.value
        fetchTask = nil
    }

    private func updateTickerDeltas(_ snapshot: Snapshot) {
        for item in snapshot.tickerItems(now: Date()) {
            guard let value = item.numeric else { continue }
            if let old = tickerBaseline[item.id], old != value { tickerDelta[item.id] = value - old }
            tickerBaseline[item.id] = value
        }
    }

    /// Ticker items with their change arrows.
    func tickerItems() -> [TickerItem] {
        (snapshot?.tickerItems(now: now) ?? []).map { item in
            var item = item
            item.delta = tickerDelta[item.id]
            return item
        }
    }

    /// Shows a fixed snapshot without a backend (used by `--preview`).
    func preview(_ snapshot: Snapshot) {
        self.snapshot = snapshot
        lastFetched = Date()
        now = Date()
    }

    func session(for slot: String) -> [String: String]? { sessions[slot] }

    /// Saves a custom card order (source ids) and re-renders everything.
    func setSourceOrder(_ ids: [String]?) {
        if let ids { UserDefaults.standard.set(ids, forKey: "sourceOrder") }
        else { UserDefaults.standard.removeObject(forKey: "sourceOrder") }
        let current = snapshot
        snapshot = current   // same value, but observers (panel, ticker) refresh
    }

    private func pushPreferences() async {
        guard let client else { return }
        do { try await client.putPreferences(disabled: claudeEnabled ? [] : ["claude"]) }
        catch { NSLog("AgentMeterBar preferences push: %@", String(describing: error)) }
    }

    /// Reads 即梦 membership / credit detail from its own page (hidden web view).
    func observeDreamina() async {
        let list = sessions.filter { ConnectionManager.provider(ofSlot: $0.key) == "dreamina" }
            .sorted { ConnectionManager.order(ofSlot: $0.key) < ConnectionManager.order(ofSlot: $1.key) }
            .map { (slot: $0.key, session: $0.value) }
        guard let client else { return }
        let result: [[String: Any]]? = list.isEmpty ? [] : await DreaminaMonitor.shared.observe(list)
        guard let observations = result else { return }   // another run is in progress
        do {
            try await client.putObservations(observations)
            await fetch(force: false)
        } catch {
            NSLog("AgentMeterBar observation push: %@", String(describing: error))
        }
    }

    func cacheSession(_ id: String, _ session: [String: String]?) {
        sessions[id] = session
    }

    private func pushSessions() async {
        guard let client else { return }
        do { try await client.putSessions(sessions) }
        catch { NSLog("AgentMeterBar session push: %@", String(describing: error)) }
    }

    /// After a website login is saved or removed.
    func syncSessionsAndRefresh() {
        Task {
            await pushSessions()
            await fetch(force: true)
            await observeDreamina()
        }
    }

    func setLaunchAtLogin(_ on: Bool) {
        do {
            if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
        } catch {
            errorMessage = "无法更改开机启动：\(error.localizedDescription)"
        }
        launchAtLogin = SMAppService.mainApp.status == .enabled
    }

    func shutdown() {
        loops.forEach { $0.cancel() }
        backend.stop()
    }

    // MARK: Menu bar label

    var menuBarText: String? {
        guard let snapshot else { return nil }
        switch menuBarMode {
        case .iconOnly: return nil
        case .tightest, .ticker, .flip:
            return snapshot.tightestQuota.map { Fmt.percent($0.remaining.rounded()) }
        case .todayTokens:
            return snapshot.history?.metric("tokens")?.value["periods"]["today"]["totals"]["total_tokens"].double
                .map(Fmt.tokens)
        }
    }

    var menuBarSymbol: String {
        if errorMessage != nil && snapshot == nil { return "exclamationmark.triangle" }
        guard let r = snapshot?.tightestQuota?.remaining else { return "gauge.with.dots.needle.33percent" }
        if r < 20 { return "gauge.with.dots.needle.0percent" }
        if r < 50 { return "gauge.with.dots.needle.33percent" }
        if r < 80 { return "gauge.with.dots.needle.50percent" }
        return "gauge.with.dots.needle.67percent"
    }
}
