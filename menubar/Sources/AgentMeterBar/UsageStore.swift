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

    var snapshot: Snapshot? { didSet { refreshDisplaySnapshot() } }
    /// `snapshot` with other devices' accounts folded in: what every view shows.
    private(set) var displaySnapshot: Snapshot?
    /// `--preview` renders a fixed snapshot and must never reach a real backend.
    /// Rendering every tab and theme takes minutes, well past the refresh
    /// interval, so without this the panel would quietly swap the demo data
    /// for the user's own accounts halfway through.
    var isPreview = false
    /// Latest GET /v1/budget payload; refreshed on the snapshot cadence.
    var budget: BudgetStatus?
    /// Login slots whose short-lived token is being renewed in a hidden window.
    var renewingSlots: Set<String> = []
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
            Task {
                // Startup skips disabled sources; turning one back on loads
                // its slots now (still without a Keychain prompt).
                if claudeEnabled { await reloadStoredSessions() }
                await pushPreferences()
                await fetch(force: true)
            }
        }
    }
    /// Third-party global-reset polling can be switched off.
    var forecastEnabled: Bool {
        didSet {
            UserDefaults.standard.set(forecastEnabled, forKey: "forecastEnabled")
            Task { await pushPreferences(); await fetch(force: true) }
        }
    }
    /// Low-resource mode (E4): the backend triples its snapshot cache TTL and
    /// skips the ledgers listed in `skipLedgersLowResource`.
    var lowResourceMode: Bool {
        didSet {
            UserDefaults.standard.set(lowResourceMode, forKey: "lowResourceMode")
            Task { await pushPreferences(); await fetch(force: true) }
        }
    }
    var skipLedgersLowResource: [String] {
        didSet {
            UserDefaults.standard.set(skipLedgersLowResource, forKey: "skipLedgersLowResource")
            Task { await pushPreferences(); await fetch(force: true) }
        }
    }
    /// Accounts with a "claim now" request in flight.
    var claimingSlots: Set<String> = []
    /// A "claim every account now" request is in flight.
    var claimingAll = false
    /// Trophies waiting for their celebration, and how many were shown in this run.
    var pendingUnlocks: [Unlock] = []
    var shownUnlocks = 0
    /// Medal or card the user opened from the binder.
    var detailTrophy: Unlock?
    var launchAtLogin: Bool = SMAppService.mainApp.status == .enabled
    /// Cadence for the background cloud-sync loop. Device-local: one Mac can
    /// sync every five minutes while another syncs once a day.
    var syncInterval: SyncInterval {
        didSet {
            syncInterval.store()
            startSyncLoop()
        }
    }
    /// True while a manual or automatic sync round is in flight.
    var syncRunning = false
    /// Last sync result or error, shown in the multi-device window.
    var syncMessage: String?
    /// Last successful sync, if any.
    var lastSyncAt: Date?
    /// Local + remote projection from GET /v1/sync/history. The account view
    /// uses its quota rows to show observations that came from another Mac.
    var syncHistory: JSON? { didSet { refreshDisplaySnapshot() } }
    /// Device-local: whether the shared preferences (theme, alert threshold,
    /// card order, menu bar, budget) follow the other devices.
    var syncPreferencesEnabled: Bool {
        didSet { UserDefaults.standard.set(syncPreferencesEnabled, forKey: SyncPreferenceSync.enabledKey) }
    }
    /// What this Mac is called in the sync space: its computer name until the
    /// user renames it in the sync window.
    var syncDeviceName: String {
        didSet { syncDeviceName = SyncConfigurationStore.setDeviceName(syncDeviceName) }
    }

    @ObservationIgnored private let backend = BackendProcess()
    /// Read-only accessor for windows that talk to the backend directly.
    var backendClient: BackendClient? { client }
    @ObservationIgnored private var client: BackendClient?
    @ObservationIgnored private var loops: [Task<Void, Never>] = []
    @ObservationIgnored private var syncTask: Task<Void, Never>?
    @ObservationIgnored private var fetchTask: Task<Void, Never>?
    @ObservationIgnored private var wakeObserver: NSObjectProtocol?
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
        forecastEnabled = d.object(forKey: "forecastEnabled") as? Bool ?? true
        // Claiming stopped being a setting: the old switch and daily time are
        // forgotten rather than left behind in preferences.
        for stale in ["autoClaimEnabled", "claimTime"] where d.object(forKey: stale) != nil {
            d.removeObject(forKey: stale)
        }
        lowQuotaThreshold = d.object(forKey: "lowQuotaThreshold") as? Double ?? 20
        lowResourceMode = d.object(forKey: "lowResourceMode") as? Bool ?? false
        skipLedgersLowResource = d.stringArray(forKey: "skipLedgersLowResource") ?? []
        syncInterval = SyncInterval.stored(in: d)
        syncPreferencesEnabled = SyncPreferenceSync.enabled(in: d)
        syncDeviceName = SyncConfigurationStore.deviceName(in: d)
    }

    var projectDirectory: URL? { client?.project }
    var isBusy: Bool { phase != .idle }

    func bootstrap() async {
        if isPreview { return }
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
        await loadSyncHistory()
        startLoops()
        // A paired device catches up first thing; the interval only decides
        // what happens afterwards.
        Task { await syncOnTimer() }
        // 会话活动 uses its own lightweight endpoint and cadence.
        ActivityTracker.shared.start()
        loops.append(Task { [weak self] in
            while !Task.isCancelled {
                await self?.syncModelCatalog()
                try? await Task.sleep(for: .seconds(6 * 60 * 60))
            }
        })
        // Saved website logins load in the background, without any Keychain
        // prompt: only enabled sources are read non-interactively; slots that
        // need authorization wait for an explicit user connect action.
        await reloadStoredSessions()
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

    /// Keep model ids and public prices current without touching user edits.
    /// A failed sync is silent here: the last good catalogue remains usable,
    /// and the price window exposes its staleness when the user wants detail.
    private func syncModelCatalog() async {
        guard let client else { return }
        do {
            let result = try await client.syncPrices()
            if result["status"].string == "updated" {
                await fetch(force: true)
                try? await client.petEvent(["kind": "prices_synced"])
            }
        } catch {
            NSLog("AgentMeterBar model catalogue sync: %@", String(describing: error))
        }
    }

    private func startLoops() {
        startSyncLoop()
        // A laptop that just woke up slept through its interval: catch up now.
        wakeObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.wakeSync() }
        }
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

    // MARK: - Cloud sync

    /// A background round: at launch, after wake, and on the interval. It only
    /// runs for a paired device whose automatic sync is on; "关闭自动同步"
    /// means nothing happens until the user presses the button.
    private func syncOnTimer() async {
        guard !isPreview, syncInterval.seconds != nil, SyncConfigurationStore.load() != nil else { return }
        await syncNow(automatic: true)
    }

    private func wakeSync() {
        Task { await syncOnTimer() }
    }

    /// One manual or automatic sync round. Manual and timer callers share the
    /// same guard, so an auto round never overlaps a button press.
    @discardableResult
    func syncNow(automatic: Bool = false) async -> SyncReport? {
        guard !syncRunning else { return nil }
        guard let config = SyncConfigurationStore.load() else {
            if !automatic { syncMessage = "尚未加入同步空间，请先完成配对。" }
            return nil
        }
        guard let client else {
            if !automatic { syncMessage = "本机后端尚未就绪，请稍后再试。" }
            return nil
        }
        // A click can land in the second before the bundled backend binds
        // 127.0.0.1:8769 (launch, or any restart). Wait for that bootstrap
        // instead of surfacing "无法连接本机后端" from a healthy app.
        if phase == .starting {
            if !automatic { syncMessage = "本机后端启动中，正在等待…" }
            for _ in 0..<60 {
                if phase != .starting { break }
                try? await Task.sleep(for: .milliseconds(250))
            }
        }
        guard await client.healthy() else {
            if !automatic { syncMessage = "本机后端尚未就绪，请稍后再试。" }
            return nil
        }
        guard let url = URL(string: config.baseURL) else {
            syncMessage = "同步服务地址无效。"
            return nil
        }

        syncRunning = true
        if !automatic { syncMessage = "正在同步…" }
        defer { syncRunning = false }

        do {
            let transport = try SyncService(baseURL: url)
            let keys = try SyncKeys(masterKey: config.masterKey, spaceID: config.spaceID)
            let runner = SyncRunner(transport: transport, keys: keys, deviceID: config.deviceID)
            // Whatever changed here since the last round gets this round's
            // stamp; the other devices compare stamps before they adopt it.
            var settings = sharedSettings()
            var state = SyncPreferenceSync.load()
            let adopt = !state.started && UserDefaults.standard.bool(forKey: SyncPreferenceSync.adoptKey)
            settings.changedAt = SyncPreferenceSync.noting(settings.values, at: Date().timeIntervalSince1970,
                                                           state: &state)
            let coordinator = SyncCoordinator(backend: client, runner: runner, settings: settings,
                                              deviceName: syncDeviceName, appVersion: Self.appVersion)
            let report = try await coordinator.run()
            if syncPreferencesEnabled {
                for carried in report.remoteSettings {
                    if let patch = SyncPreferenceSync.accepted(carried.settings, local: sharedSettings(),
                                                               state: state, adopt: adopt) {
                        await applySynced(patch)
                        SyncPreferenceSync.applied(patch, to: &state)
                    }
                }
            }
            // What the other devices changed is this device's value now.
            state.local = sharedSettings().values
            SyncPreferenceSync.save(state)
            lastSyncAt = Date()
            syncMessage = Self.summary(for: report)
            await loadSyncHistory()
            return report
        } catch {
            syncMessage = (automatic ? "自动同步失败：" : "") + Self.message(for: error)
            NSLog("AgentMeterBar sync: %@", String(describing: error))
            return nil
        }
    }

    /// The preferences this device shares with the space, as they are now.
    private func sharedSettings() -> SyncSettings {
        var settings = SyncSettings()
        settings.theme = theme.rawValue
        settings.lowQuotaThreshold = lowQuotaThreshold
        settings.alertsEnabled = notificationsEnabled
        settings.menuBarMode = menuBarMode.rawValue
        settings.sourceOrder = UserDefaults.standard.stringArray(forKey: "sourceOrder") ?? []
        settings.budget = sharedBudget
        return settings
    }

    /// The budget amounts that are set, in CNY. Empty means no budget, and
    /// travels too: clearing a budget on one device clears it everywhere.
    private var sharedBudget: [String: Double] {
        let config = budget?.json["config"] ?? .null
        var out: [String: Double] = [:]
        for key in ["daily_cny", "weekly_cny", "anomaly_multiplier"] {
            if let value = config[key].double, value > 0 { out[key] = value }
        }
        return out
    }

    /// Writes a newer value from another device through this store's own
    /// setters, exactly as if the user had picked it here.
    private func applySynced(_ patch: SyncSettings) async {
        if let name = patch.theme, let value = PanelTheme(rawValue: name) { theme = value }
        if let threshold = patch.lowQuotaThreshold, (0...100).contains(threshold) { lowQuotaThreshold = threshold }
        if let alerts = patch.alertsEnabled { notificationsEnabled = alerts }
        if let name = patch.menuBarMode, let value = MenuBarMode(rawValue: name) { menuBarMode = value }
        if let order = patch.sourceOrder { setSourceOrder(order.isEmpty ? nil : order) }
        if let amounts = patch.budget, let client {
            let multiplier = amounts["anomaly_multiplier"].map { String($0) }
                ?? budget?.configMultiplier ?? "2.0"
            _ = try? await client.putBudget(daily: amounts["daily_cny"].map { String($0) },
                                            weekly: amounts["weekly_cny"].map { String($0) },
                                            multiplier: multiplier)
            await refreshBudget()
        }
    }

    /// Called by the pairing window when this device joined a space, or
    /// another device joined its space. The first round runs right away, so
    /// the merge shows up without a button press or a wait for the interval.
    func pairingFinished() {
        startSyncLoop()
        Task { await syncNow() }
    }

    /// Leaves the sync space completely: this device's blob is removed from
    /// the service, every other device is forgotten here, and the key is
    /// dropped. What cannot be removed is said out loud, never assumed.
    func unpair() async {
        syncTask?.cancel()
        syncTask = nil
        var note = "已退出同步空间：本机上传的数据已从服务端删除，其他设备的数据已从本机清除。"
        if let client { try? await client.resetSync() }
        if let config = SyncConfigurationStore.load() {
            var left = false
            if let url = URL(string: config.baseURL) {
                do {
                    let transport = try SyncService(baseURL: url)
                    let keys = try SyncKeys(masterKey: config.masterKey, spaceID: config.spaceID)
                    try await SyncRunner(transport: transport, keys: keys, deviceID: config.deviceID).leave()
                    left = true
                } catch {
                    NSLog("AgentMeterBar sync leave: %@", String(describing: error))
                }
            }
            if !left {
                note = "已退出同步空间，其他设备的数据已从本机清除；但连不上同步服务，服务端上本机的数据没有删除。重新配对后可以在设备列表里移除它。"
            }
        }
        SyncConfigurationStore.clear()
        SyncPreferenceSync.reset()
        syncHistory = nil
        lastSyncAt = nil
        syncMessage = note
    }

    /// Takes another device out of the space: its blob is deleted from the
    /// service and what it sent is forgotten here.
    func forgetSyncDevice(_ device: String) async {
        guard let config = SyncConfigurationStore.load(), device != config.deviceID else { return }
        let name = syncHistory?["devices"].array.first { $0["device"].string == device }?["name"].string ?? ""
        let shown = SyncConfigurationStore.label(name: name, device: device)
        guard let url = URL(string: config.baseURL) else {
            syncMessage = "同步服务地址无效。"
            return
        }
        do {
            let transport = try SyncService(baseURL: url)
            let keys = try SyncKeys(masterKey: config.masterKey, spaceID: config.spaceID)
            try await SyncRunner(transport: transport, keys: keys, deviceID: config.deviceID).remove(device: device)
            if let client { try await client.forgetSyncDevice(device) }
            await loadSyncHistory()
            syncMessage = "已移除「\(shown)」：它上传的数据已从服务端和本机删除。"
        } catch {
            syncMessage = "移除设备失败：" + Self.message(for: error)
            NSLog("AgentMeterBar sync forget %@: %@", device, String(describing: error))
        }
    }

    static var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
    }

    /// Restarts the sleep loop whenever the interval changes. Only one timer
    /// task exists; turning automatic sync off simply leaves it nil.
    private func startSyncLoop() {
        syncTask?.cancel()
        syncTask = nil
        guard !isPreview, let seconds = syncInterval.seconds else { return }
        let nanos = UInt64(seconds * 1_000_000_000)
        syncTask = Task { [weak self] in
            while !Task.isCancelled {
                do { try await Task.sleep(nanoseconds: nanos) }
                catch { return }
                guard !Task.isCancelled else { return }
                await self?.syncNow(automatic: true)
            }
        }
    }

    /// Read the local + remote projection. The account view uses this to
    /// display quota observations that came from another device.
    func loadSyncHistory() async {
        guard let client, SyncConfigurationStore.load() != nil else {
            syncHistory = nil
            return
        }
        do { syncHistory = try await client.syncHistory() }
        catch { NSLog("AgentMeterBar sync history: %@", String(describing: error)) }
    }

    private static func summary(for report: SyncReport) -> String {
        var text = "已上传本机用量"
        if report.localQuotaRows > 0 { text += "与 \(report.localQuotaRows) 条额度" }
        text += "，空间内共 \(report.devices) 台设备"
        if !report.importedDevices.isEmpty {
            text += "，合并了 \(report.importedDevices.count) 台其他设备"
            var parts: [String] = []
            if report.remoteQuotaRows > 0 { parts.append("\(report.remoteQuotaRows) 条额度") }
            if report.remoteAccountRows > 0 { parts.append("\(report.remoteAccountRows) 个账户") }
            if report.remoteRewardRows > 0 { parts.append("\(report.remoteRewardRows) 天签到记录") }
            if !parts.isEmpty { text += "（" + parts.joined(separator: "、") + "）" }
        }
        if !report.failedDevices.isEmpty {
            text += "；\(report.failedDevices.count) 台设备的密文无法读取（对方版本较旧，或不在同一空间）"
        }
        return text + "。"
    }

    private static func message(for error: Error) -> String {
        if let error = error as? SyncError {
            switch error {
            case .notConfigured: return "同步配置不完整"
            case .unauthorized: return "空间凭证无效，请重新配对"
            case .notFound: return "空间或设备不存在"
            case .invalidResponse: return "同步服务返回了无法识别的数据"
            case .transport: return "无法连接同步服务，请检查地址和网络"
            case .cryptoFailed: return "同步数据无法解密，请检查两台设备是否在同一空间"
            case .rejected(let code): return "同步服务返回：\(code)"
            }
        }
        if let error = error as? BackendError {
            return error.localizedDescription
        }
        return "操作失败，请稍后重试"
    }

    /// Called when the panel opens; only fetches when the data is getting old.
    func panelOpened() {
        now = Date()
        if isPreview { return }
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
                Fmt.useExchangeRate(result.raw["exchange_rate"])
                snapshot = result
                updateTickerDeltas(result)
                lastFetched = Date()
                errorMessage = nil
                Notifier.shared.evaluate(result, store: self, now: Date())
                await refreshBudget()
                Notifier.shared.rewardResults(result)
                if let collection = result.collection {
                    let fresh = UnlockTracker.newUnlocks(in: collection)
                    if !fresh.isEmpty {
                        pendingUnlocks.append(contentsOf: fresh)
                        if notificationsEnabled { Notifier.shared.unlocked(fresh, in: collection) }
                    }
                }
                TokenRenewer.shared.consider(result)
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

    /// Budget follows the snapshot cadence. The backend reuses its current
    /// snapshot (no extra collection); events dedup through the Notifier's
    /// fired set, so recovery back-fills never re-notify the same day/week.
    private func refreshBudget() async {
        guard let client else { return }
        do {
            let status = BudgetStatus(try await client.getBudget())
            budget = status
            Notifier.shared.evaluateBudget(status, store: self, now: Date())
        } catch {
            NSLog("AgentMeterBar budget fetch: %@", String(describing: error))
        }
    }

    /// Settings window save: PUT the config, then re-read the computed state.
    func saveBudget(daily: String?, weekly: String?, multiplier: String) async throws {
        guard let client else { throw BackendError.unreachable }
        _ = try await client.putBudget(daily: daily, weekly: weekly, multiplier: multiplier)
        await refreshBudget()
    }

    // MARK: - E2/E3/E4 projections

    var projects: ProjectsFeed?
    var weekReport: PeriodReport?
    var monthReport: PeriodReport?
    var statusFeed: StatusFeed?
    @ObservationIgnored private var projectsAt = Date.distantPast
    @ObservationIgnored private var reportAt: [String: Date] = [:]
    @ObservationIgnored private var statusAt = Date.distantPast

    func loadProjects(force: Bool = false) async {
        guard let client else { return }
        if !force && Date().timeIntervalSince(projectsAt) < 120 { return }
        projectsAt = Date()
        do { projects = ProjectsFeed(try await client.getProjects()) }
        catch { NSLog("AgentMeterBar projects fetch: %@", String(describing: error)) }
    }

    func loadReport(kind: String, force: Bool = false) async {
        guard let client else { return }
        let last = reportAt[kind] ?? .distantPast
        if !force && Date().timeIntervalSince(last) < 60 { return }
        reportAt[kind] = Date()
        do {
            let report = PeriodReport(try await client.getPeriods(kind: kind))
            if kind == "week" { weekReport = report } else { monthReport = report }
        } catch { NSLog("AgentMeterBar periods fetch: %@", String(describing: error)) }
    }

    func loadStatus(force: Bool = false) async {
        guard let client else { return }
        if !force && Date().timeIntervalSince(statusAt) < 30 { return }
        statusAt = Date()
        do { statusFeed = StatusFeed(try await client.getStatus()) }
        catch { NSLog("AgentMeterBar status fetch: %@", String(describing: error)) }
    }

    private func refreshDisplaySnapshot() {
        displaySnapshot = snapshot.map { SyncMerge.merged($0, history: syncHistory) }
    }

    private func updateTickerDeltas(_ snapshot: Snapshot) {
        for item in (displaySnapshot ?? snapshot).tickerItems(now: Date()) {
            guard let value = item.numeric else { continue }
            if let old = tickerBaseline[item.id], old != value { tickerDelta[item.id] = value - old }
            tickerBaseline[item.id] = value
        }
    }

    /// Ticker items with their change arrows.
    func tickerItems() -> [TickerItem] {
        (displaySnapshot?.tickerItems(now: now) ?? []).map { item in
            var item = item
            item.delta = tickerDelta[item.id]
            return item
        }
    }

    /// Shows a fixed snapshot without a backend (used by `--preview`).
    func preview(_ snapshot: Snapshot) {
        Fmt.useExchangeRate(snapshot.raw["exchange_rate"])
        self.snapshot = snapshot
        lastFetched = Date()
        now = Date()
        isPreview = true
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
        var off: [String] = []
        if !claudeEnabled { off.append("claude") }
        if !forecastEnabled { off.append("reset_forecast") }
        do { try await client.putPreferences(disabled: off, lowResource: lowResourceMode,
                                             skipLedgers: skipLedgersLowResource) }
        catch { NSLog("AgentMeterBar preferences push: %@", String(describing: error)) }
    }

    func openTrophy(_ unlock: Unlock) {
        withAnimation(.spring(response: 0.35)) { detailTrophy = unlock }
    }

    /// Closes the current celebration and moves to the next one.
    func dismissUnlock() {
        guard !pendingUnlocks.isEmpty else { return }
        pendingUnlocks.removeFirst()
        shownUnlocks = pendingUnlocks.isEmpty ? 0 : shownUnlocks + 1
    }

    /// The user's "领取" button: claims one account now, then shows the result.
    /// Nothing claims on its own — this and `claimAllRewards()` are the only
    /// two ways a provider account is written to.
    func claimReward(_ slot: String) async {
        guard let client, !claimingSlots.contains(slot) else { return }
        claimingSlots.insert(slot)
        defer { claimingSlots.remove(slot) }
        do { try await client.claimReward(slot) }
        catch { NSLog("AgentMeterBar claim %@: %@", slot, String(describing: error)) }
        await fetch(force: false)
    }

    /// The settings menu's "领取每日积分" button: every account at once.
    func claimAllRewards() async {
        guard let client, !claimingAll else { return }
        claimingAll = true
        defer { claimingAll = false }
        do {
            let accounts = try await client.claimReward()["accounts"].array
            let claimed = accounts.reduce(0.0) { $0 + ($1["claimed_credits_today"].double ?? 0) }
            let succeeded = accounts.contains { account in
                account["claims_today"].array.contains { $0["result"].string == "ok" }
            }
            if claimed == 0 && !succeeded && notificationsEnabled {
                Notifier.shared.claimNothingToday(blocked: accounts.contains { $0["status"].string != "available" })
            }
        } catch { NSLog("AgentMeterBar claim all: %@", String(describing: error)) }
        await fetch(force: false)
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

    /// Merges the non-interactively readable sessions of enabled sources into
    /// memory and hands them to the backend. Never prompts; failed slots are
    /// logged by ConnectionManager and left for an explicit connect action.
    private func reloadStoredSessions() async {
        let stored = await ConnectionManager.shared.storedSessions()
        guard !stored.isEmpty else { return }
        sessions.merge(stored) { _, new in new }
        await pushSessions()
        await fetch(force: true)
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
        syncTask?.cancel()
        if let wakeObserver {
            NSWorkspace.shared.notificationCenter.removeObserver(wakeObserver)
            self.wakeObserver = nil
        }
        backend.stop()
    }

    // MARK: Menu bar label

    var menuBarText: String? {
        guard let snapshot = displaySnapshot else { return nil }
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
        guard let r = displaySnapshot?.tightestQuota?.remaining else { return "gauge.with.dots.needle.33percent" }
        if r < 20 { return "gauge.with.dots.needle.0percent" }
        if r < 50 { return "gauge.with.dots.needle.33percent" }
        if r < 80 { return "gauge.with.dots.needle.50percent" }
        return "gauge.with.dots.needle.67percent"
    }
}
