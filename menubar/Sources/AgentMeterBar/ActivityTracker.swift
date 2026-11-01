import Foundation
import Observation

/// Owns the 会话活动 refresh loop, independent from the snapshot poll.
///
/// Cadence (ActivityCadence): 5 s while the panel shows the activity tab,
/// 15 s in the background while something is running, 120 s idle. Fetches
/// hit GET /v1/activity only — a lightweight recent-window scan that can
/// never trigger full account collection.
@MainActor @Observable
final class ActivityTracker {
    static let shared = ActivityTracker()

    var feed: ActivityFeed?
    var errorMessage: String?
    private(set) var lastFetched: Date?
    /// Whether the activity tab is currently on screen (drives the fast lane).
    var panelVisible = false

    @ObservationIgnored private var loop: Task<Void, Never>?
    @ObservationIgnored private var fetchTask: Task<Void, Never>?

    /// 项目别名重命名（路径 → 名称），仅存本机 UserDefaults。
    @ObservationIgnored private(set) var aliases: [String: String]

    private init() {
        aliases = UserDefaults.standard.dictionary(forKey: "activityProjectAliases")
            as? [String: String] ?? [:]
    }

    func start() {
        guard loop == nil else { return }
        loop = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                let interval = ActivityCadence.interval(panelVisible: self.panelVisible,
                                                        hasRunning: self.feed?.hasRunning ?? false)
                try? await Task.sleep(for: .seconds(interval))
                await self.fetch()
            }
        }
    }

    func stop() {
        loop?.cancel()
        loop = nil
    }

    /// Offline preview injection (--preview renders every tab without a backend).
    func preview(_ feed: ActivityFeed) {
        self.feed = feed
        lastFetched = Date()
    }

    func fetch() async {
        guard fetchTask == nil, let client = UsageStore.shared.backendClient else { return }
        let task = Task { @MainActor in
            do {
                feed = try await client.activity()
                errorMessage = nil
                lastFetched = Date()
            } catch {
                // Keep the last good feed; the view shows a quiet hint.
                errorMessage = error.localizedDescription
            }
        }
        fetchTask = task
        await task.value
        fetchTask = nil
    }

    /// Immediate fetch when the user opens the activity tab.
    func panelAppeared() {
        panelVisible = true
        Task {
            if feed == nil || lastFetched.map({ Date().timeIntervalSince($0) > 3 }) == true {
                await fetch()
            }
        }
    }

    func panelDisappeared() {
        panelVisible = false
    }

    // MARK: 项目别名

    func renameProject(path: String, to name: String) {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            aliases.removeValue(forKey: path)
        } else {
            aliases[path] = trimmed
        }
        UserDefaults.standard.set(aliases, forKey: "activityProjectAliases")
    }

    func alias(for path: String?) -> String? {
        guard let path else { return nil }
        return aliases[path]
    }
}
