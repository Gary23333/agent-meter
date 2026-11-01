import Foundation

/// Session/turn activity feed from GET /v1/activity (schema_version 1).
///
/// Status vocabulary mirrors the backend contract: `running` needs fresh
/// evidence, terminal statuses come only from explicit events, and a
/// recency-only row never claims success (未知 ≠ 失败).
enum ActivityStatus: String, Comparable {
    case running
    case suspectedEnded = "suspected_ended"
    case completed
    case cancelled
    case failed
    case unknown

    var label: String {
        switch self {
        case .running: return "进行中"
        case .suspectedEnded: return "疑似结束"
        case .completed: return "已完成"
        case .cancelled: return "已取消"
        case .failed: return "失败"
        case .unknown: return "未知"
        }
    }

    /// Terminal statuses sort below live ones; unknown sinks last.
    var rank: Int {
        switch self {
        case .running: return 0
        case .suspectedEnded: return 1
        case .completed: return 2
        case .cancelled: return 3
        case .failed: return 4
        case .unknown: return 5
        }
    }

    static func < (lhs: ActivityStatus, rhs: ActivityStatus) -> Bool { lhs.rank < rhs.rank }
}

/// What one row represents — and what it can NOT claim:
/// 回合完成 ≠ 整个会话完成, 子代理完成 ≠ 根任务完成, 停止写入 ≠ 成功.
enum ActivityGranularity: String {
    case imageCall = "image_call"
    case turn
    case steps
    case turnSteps = "turn_steps"
    case recentActivity = "recent_activity"

    var label: String {
        switch self {
        case .imageCall: return "生图调用"
        case .turn: return "回合"
        case .steps: return "步骤"
        case .turnSteps: return "回合/步骤"
        case .recentActivity: return "最近活动"
        }
    }

    var caveat: String {
        switch self {
        case .imageCall: return "调用状态明确；不代表整个 Codex 编码会话"
        case .turn: return "回合完成 ≠ 整个会话完成"
        case .steps: return "步骤/子代理完成 ≠ 根任务完成"
        case .turnSteps: return "回合终态明确；不推断整个会话成败"
        case .recentActivity: return "停止写入不能算成功，应用退出也不能算失败"
        }
    }
}

struct ActivityTokens {
    let freshInput: Double
    let output: Double
    let reasoning: Double
    let cacheRead: Double
    let cacheWrite: Double
    let total: Double

    init(_ json: JSON) {
        freshInput = json["fresh_input"].double ?? 0
        output = json["output"].double ?? 0
        reasoning = json["reasoning"].double ?? 0
        cacheRead = json["cache_read"].double ?? 0
        cacheWrite = json["cache_write"].double ?? 0
        total = json["total_tokens"].double ?? 0
    }

    /// 缓存读 + 写占输入侧的比例，与用量页同口径。
    var cacheHitRate: Double? {
        let base = freshInput + cacheRead + cacheWrite
        return base > 0 ? cacheRead / base : nil
    }
}

struct ActivityTurn: Identifiable {
    let turn: String
    let startedAt: Date?
    let endedAt: Date?
    let status: ActivityStatus
    let model: String?
    let tokens: Double
    let steps: Int?

    var id: String { turn }
}

struct ActivityRow: Identifiable {
    let app: String
    let granularity: ActivityGranularity
    let status: ActivityStatus
    let statusBasis: String
    let projectAlias: String?
    let projectPath: String?
    let sessionID: String
    let subagent: Bool
    let startedAt: Date?
    let lastEventAt: Date?
    let lastModel: String?
    let requests: Int?
    let tokens: ActivityTokens?
    let estimatedCostUSD: Double?
    let notes: String?
    let turnStatuses: [String: Int]
    let lastTurnStatus: ActivityStatus?
    let turns: Int?
    let recentTurns: [ActivityTurn]
    let calls: Int?
    let failedCalls: Int?
    let generatingCalls: Int?

    init(_ json: JSON) {
        app = json["app"].string ?? "unknown"
        granularity = ActivityGranularity(rawValue: json["granularity"].string ?? "") ?? .recentActivity
        status = ActivityStatus(rawValue: json["status"].string ?? "") ?? .unknown
        statusBasis = json["status_basis"].string ?? "recency"
        projectAlias = json["project_alias"].string
        projectPath = json["project_path"].string
        sessionID = json["session_id"].string ?? ""
        subagent = json["subagent"].bool ?? false
        startedAt = json["started_at"].date
        lastEventAt = json["last_event_at"].date
        lastModel = json["last_model"].string
        requests = json["requests"].double.map(Int.init)
        tokens = json["tokens"].isNull ? nil : ActivityTokens(json["tokens"])
        estimatedCostUSD = json["estimated_cost_usd"].double
        notes = json["notes"].string
        turnStatuses = json["turn_statuses"].object
            .compactMapValues { $0.double.map(Int.init) }
        lastTurnStatus = ActivityStatus(rawValue: json["last_turn_status"].string ?? "")
        turns = json["turns"].double.map(Int.init)
        recentTurns = json["recent_turns"].array.map { turn in
            ActivityTurn(turn: turn["turn"].string ?? "?", startedAt: turn["started_at"].date,
                         endedAt: turn["ended_at"].date,
                         status: ActivityStatus(rawValue: turn["status"].string ?? "") ?? .unknown,
                         model: turn["model"].string,
                         tokens: turn["tokens"].double ?? 0,
                         steps: turn["steps"].double.map(Int.init))
        }
        calls = json["calls"].double.map(Int.init)
        failedCalls = json["failed_calls"].double.map(Int.init)
        generatingCalls = json["generating_calls"].double.map(Int.init)
    }

    var id: String { app + "/" + sessionID }

    var appLabel: String {
        app == "codex_images" ? "Codex 生图" : Catalog.appLabel(app)
    }

    /// User rename first, then the backend alias, then an honest placeholder.
    func displayName(aliases: [String: String]) -> String {
        if let path = projectPath, let renamed = aliases[path] { return renamed }
        if let projectAlias { return projectAlias }
        return "未归属"
    }

    var hasTurnDetail: Bool { !recentTurns.isEmpty || !turnStatuses.isEmpty }
}

struct ActivitySourceMeta {
    let status: String
    let reason: String?
    let activities: Int

    init(_ json: JSON) {
        status = json["status"].string ?? "error"
        reason = json["reason"].string
        activities = Int(json["activities"].double ?? 0)
    }
}

struct ActivityFeed {
    let generatedAt: Date?
    let windowHours: Int
    let idleAfterMinutes: Int
    let activities: [ActivityRow]
    let sourcesMeta: [String: ActivitySourceMeta]

    init(_ json: JSON) {
        generatedAt = json["generated_at"].date
        windowHours = Int(json["window_hours"].double ?? 24)
        idleAfterMinutes = Int(json["idle_after_minutes"].double ?? 15)
        activities = json["activities"].array.map(ActivityRow.init)
        sourcesMeta = json["sources_meta"].object.mapValues(ActivitySourceMeta.init)
    }

    var runningCount: Int { activities.filter { $0.status == .running }.count }
    var hasRunning: Bool { runningCount > 0 }

    /// Running first, then suspected, then terminal; newest activity wins ties.
    static func sorted(_ rows: [ActivityRow]) -> [ActivityRow] {
        rows.sorted {
            if $0.status != $1.status { return $0.status < $1.status }
            return ($0.lastEventAt ?? .distantPast) > ($1.lastEventAt ?? .distantPast)
        }
    }

    enum Filter: String, CaseIterable, Identifiable {
        case all, running, rest
        var id: String { rawValue }
        var label: String {
            switch self {
            case .all: return "全部"
            case .running: return "进行中"
            case .rest: return "其余"
            }
        }
        func matches(_ row: ActivityRow) -> Bool {
            switch self {
            case .all: return true
            case .running: return row.status == .running
            case .rest: return row.status != .running
            }
        }
    }
}

/// Refresh cadence (秒): panel watching the activity tab, something running
/// in the background, or fully idle. Fetching never touches /v1/refresh and
/// can not trigger full account collection — the endpoint scans only the
/// recent window.
enum ActivityCadence {
    static func interval(panelVisible: Bool, hasRunning: Bool) -> TimeInterval {
        if panelVisible { return 5 }
        if hasRunning { return 15 }
        return 120
    }
}
