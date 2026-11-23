import Foundation
import Observation
import SwiftUI

/// Processes started by local agent harnesses, from GET /v1/processes (schema_version 1).
///
/// Scope is the backend's contract: only descendants of a harness (plus orphans one left behind) are ever
/// reported, command lines arrive already redacted, and nothing here can signal or end a process.

enum ProcessKind: String {
    case shell, mcp, test, build, vcs, server, runtime, harness, other

    var label: String {
        switch self {
        case .shell: return "Shell"
        case .mcp: return "MCP"
        case .test: return "测试"
        case .build: return "构建"
        case .vcs: return "版本"
        case .server: return "服务"
        case .runtime: return "运行时"
        case .harness: return "Harness"
        case .other: return "其他"
        }
    }

    var symbol: String {
        switch self {
        case .shell: return "terminal"
        case .mcp: return "puzzlepiece.extension"
        case .test: return "checkmark.seal"
        case .build: return "hammer"
        case .vcs: return "arrow.triangle.branch"
        case .server: return "server.rack"
        case .runtime: return "curlybraces"
        case .harness: return "sparkle"
        case .other: return "circle.dotted"
        }
    }

    /// One colour per kind, shared by the list badges and the 3D nodes.
    var rgb: (Double, Double, Double) {
        switch self {
        case .shell: return (0.62, 0.67, 0.74)
        case .mcp: return (0.64, 0.48, 1.0)
        case .test: return (1.0, 0.72, 0.22)
        case .build: return (0.30, 0.58, 1.0)
        case .vcs: return (1.0, 0.46, 0.64)
        case .server: return (0.18, 0.82, 0.62)
        case .runtime: return (0.46, 0.54, 1.0)
        case .harness: return (0.85, 0.85, 0.92)
        case .other: return (0.60, 0.62, 0.68)
        }
    }

    var color: Color { Color(red: rgb.0, green: rgb.1, blue: rgb.2) }
    var nsColor: NSColor { NSColor(srgbRed: rgb.0, green: rgb.1, blue: rgb.2, alpha: 1) }
}

struct HarnessProcess: Identifiable, Equatable {
    var id: Int { pid }
    let pid: Int
    let parent: Int
    let depth: Int
    let name: String
    let command: String
    let kind: ProcessKind
    let state: String
    let cpu: Double
    let rss: Double
    let uptime: Double
    let ports: [Int]
    let orphaned: Bool
    /// A harness binary below the group's root (a wrapper's native child): counted in the totals, not as a spawned process.
    let core: Bool

    init(_ j: JSON) {
        pid = Int(j["pid"].double ?? 0)
        parent = Int(j["ppid"].double ?? 0)
        depth = max(1, Int(j["depth"].double ?? 1))
        name = j["name"].string ?? "?"
        command = j["command"].string ?? ""
        kind = ProcessKind(rawValue: j["kind"].string ?? "") ?? .other
        state = j["state"].string ?? "unknown"
        cpu = j["cpu_percent"].double ?? 0
        rss = j["rss_bytes"].double ?? 0
        uptime = j["uptime_seconds"].double ?? 0
        ports = j["ports"].array.compactMap { $0.double.map { Int($0) } }
        orphaned = j["orphaned"].bool ?? false
        core = j["core"].bool ?? false
    }
}

struct HarnessGroup: Identifiable, Equatable {
    let id: String
    let app: String
    let label: String
    /// The harness process itself; nil for the leftovers of a harness that has exited.
    let pid: Int?
    let alive: Bool
    let uptime: Double?
    let projectPath: String?
    let projectAlias: String?
    let count: Int
    let cpu: Double
    let rss: Double
    let truncated: Bool
    let processes: [HarnessProcess]

    init(_ j: JSON) {
        app = j["app"].string ?? "unknown"
        label = j["label"].string ?? app
        pid = j["pid"].double.map { Int($0) }
        alive = j["alive"].bool ?? true
        id = app + "-" + (pid.map(String.init) ?? "left-behind")
        uptime = j["uptime_seconds"].double
        projectPath = j["project_path"].string
        projectAlias = j["project_alias"].string
        count = Int(j["process_count"].double ?? 0)
        cpu = j["cpu_percent"].double ?? 0
        rss = j["rss_bytes"].double ?? 0
        truncated = j["truncated"].bool ?? false
        processes = j["processes"].array.map(HarnessProcess.init)
    }

    /// Rows worth listing: harness cores fold into the header.
    var rows: [HarnessProcess] { processes.filter { !$0.core } }
}

struct ProcessFeed: Equatable {
    let status: String
    let reason: String?
    let groups: [HarnessGroup]
    let harnessCount: Int
    let processCount: Int
    let cpu: Double
    let rss: Double
    let generatedAt: Date?

    init(_ j: JSON) {
        status = j["status"].string ?? "unavailable"
        reason = j["reason"].string
        groups = j["harnesses"].array.map(HarnessGroup.init)
        harnessCount = Int(j["totals"]["harness_count"].double ?? 0)
        processCount = Int(j["totals"]["process_count"].double ?? 0)
        cpu = j["totals"]["cpu_percent"].double ?? 0
        rss = j["totals"]["rss_bytes"].double ?? 0
        generatedAt = j["generated_at"].date
    }

    var isAvailable: Bool { status == "available" }
}

enum ProcessFormat {
    static func memory(_ bytes: Double) -> String {
        if bytes >= 1_073_741_824 { return String(format: "%.1f GB", bytes / 1_073_741_824) }
        if bytes >= 1_048_576 { return String(format: "%.0f MB", bytes / 1_048_576) }
        return String(format: "%.0f KB", bytes / 1024)
    }

    static func cpu(_ percent: Double) -> String {
        percent >= 100 ? String(format: "%.0f%%", percent) : String(format: "%.1f%%", percent)
    }

    static func uptime(_ seconds: Double) -> String {
        let s = Int(seconds)
        if s < 60 { return "\(s) 秒" }
        if s < 3600 { return "\(s / 60) 分" }
        if s < 86_400 { return "\(s / 3600) 时 \(s % 3600 / 60) 分" }
        return "\(s / 86_400) 天 \(s % 86_400 / 3600) 时"
    }

    static func state(_ raw: String) -> String {
        ["running": "运行", "sleeping": "休眠", "idle": "空闲", "waiting": "等待", "stopped": "已暂停", "zombie": "僵尸"][raw] ?? "未知"
    }
}

/// Owns the 进程 refresh loop. Unlike the other feeds it has no background cadence at all: it polls every 3 s
/// only while the process tab is on screen, so the monitor costs nothing when nobody is looking.
@MainActor @Observable
final class ProcessTracker {
    static let shared = ProcessTracker()

    var feed: ProcessFeed?
    var errorMessage: String?
    private(set) var lastFetched: Date?

    @ObservationIgnored private var loop: Task<Void, Never>?
    @ObservationIgnored private var inFlight = false

    private init() {}

    func panelAppeared() {
        guard loop == nil else { return }
        loop = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.fetch()
                do { try await Task.sleep(for: .seconds(3)) } catch { return }
            }
        }
    }

    func panelDisappeared() {
        loop?.cancel()
        loop = nil
    }

    /// Offline preview injection (--preview renders every tab without a backend).
    func preview(_ feed: ProcessFeed) {
        self.feed = feed
        lastFetched = Date()
    }

    func fetch() async {
        guard !inFlight, !UsageStore.shared.isPreview, let client = UsageStore.shared.backendClient else { return }
        inFlight = true
        defer { inFlight = false }
        do {
            feed = try await client.processes()
            errorMessage = nil
            lastFetched = Date()
        } catch {
            errorMessage = error.localizedDescription     // keep the last good feed
        }
    }
}
