import Foundation

enum PetJSON {
    /// A JSON number. `NSNumber(1)` also bridges to `Bool`, so booleans are told apart by their CoreFoundation type.
    static func number(_ v: Any?) -> Double? {
        guard let n = v as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID() else { return nil }
        let d = n.doubleValue
        return d.isFinite ? d : nil
    }

    static func date(_ v: Any?) -> Date? { number(v).map { Date(timeIntervalSince1970: $0) } }
}

/// The parts of a PetFrame the panel shows in words and numbers (the pet itself is drawn by the web page from the
/// same frame). Parsing is total: a field that is missing or of the wrong type simply reads as "not known".
struct PetStatus: Equatable {
    struct Energy: Equatable {
        var known = false
        var remaining: Double?
        var label: String?
        var tone = "unknown"
        var resetsAt: Date?
        var stale = false
        var drivesState = false
        var scope = "all"
    }

    struct Meter: Equatable, Identifiable {
        let id: String
        let source: String
        let name: String
        let window: String
        let remaining: Double
        let tone: String
        let resetsAt: Date?
        let stale: Bool
    }

    struct Session: Equatable, Identifiable {
        var id: String { app }
        let app: String
        let label: String
        let count: Int
        let project: String?
    }

    struct Reminder: Equatable, Identifiable {
        let id: String
        let text: String
        let tone: String
        /// The panel tab the reminder points to, when it names one.
        let tab: String?
    }

    struct Event: Equatable, Identifiable {
        let id: String
        let kind: String
        let source: String?
        let text: String?
        let at: Date
    }

    var state = "idle"
    var mood = "neutral"
    var generatedAt = Date()
    var energy = Energy()
    var meters: [Meter] = []
    var activityKnown = false
    var running = 0
    var sessions: [Session] = []
    var generatingImages = 0
    var todayTokens: Double?
    var focusEndsAt: Date?
    var forecastMood: String?
    var events: [Event] = []
    var reminders: [Reminder] = []
    var reminderCount: Int { reminders.count }
    var reasons: [String] = []
    var snapshotAge: Double?
    var reaction: String?

    static func parse(_ frame: [String: Any]) -> PetStatus? {
        guard let state = frame["state"] as? String else { return nil }
        var s = PetStatus()
        s.state = state
        s.mood = frame["mood"] as? String ?? "neutral"
        s.generatedAt = PetJSON.date(frame["generated_at"]) ?? Date()
        if let e = frame["energy"] as? [String: Any] {
            s.energy = Energy(known: e["known"] as? Bool ?? false, remaining: PetJSON.number(e["remaining"]), label: e["label"] as? String,
                              tone: e["tone"] as? String ?? "unknown", resetsAt: PetJSON.date(e["resets_at"]), stale: e["stale"] as? Bool ?? false,
                              drivesState: e["drives_state"] as? Bool ?? false, scope: e["scope"] as? String ?? "all")
            if s.energy.remaining == nil { s.energy.known = false }
        }
        s.meters = (frame["meters"] as? [[String: Any]] ?? []).compactMap { m in
            guard let id = m["id"] as? String, let remaining = PetJSON.number(m["remaining"]) else { return nil }
            return Meter(id: id, source: m["source"] as? String ?? id, name: m["name"] as? String ?? id, window: m["window"] as? String ?? "",
                         remaining: remaining, tone: m["tone"] as? String ?? "unknown", resetsAt: PetJSON.date(m["resets_at"]),
                         stale: m["stale"] as? Bool ?? false)
        }
        if let a = frame["activity"] as? [String: Any] {
            s.activityKnown = a["known"] as? Bool ?? false
            s.running = Int(PetJSON.number(a["running"]) ?? 0)
            s.generatingImages = Int(PetJSON.number(a["generating_images"]) ?? 0)
            s.sessions = (a["apps"] as? [[String: Any]] ?? []).compactMap { r in
                guard let app = r["app"] as? String else { return nil }
                return Session(app: app, label: r["label"] as? String ?? app, count: Int(PetJSON.number(r["count"]) ?? 1),
                               project: r["project"] as? String)
            }
        }
        if let today = frame["today"] as? [String: Any], today["known"] as? Bool == true { s.todayTokens = PetJSON.number(today["tokens"]) }
        if let focus = frame["focus"] as? [String: Any], focus["active"] as? Bool == true { s.focusEndsAt = PetJSON.date(focus["ends_at"]) }
        if let forecast = frame["forecast"] as? [String: Any], forecast["known"] as? Bool == true { s.forecastMood = forecast["mood"] as? String }
        s.events = (frame["events"] as? [[String: Any]] ?? []).compactMap { e in
            guard let id = e["id"] as? String, let kind = e["kind"] as? String, let at = PetJSON.date(e["at"]) else { return nil }
            return Event(id: id, kind: kind, source: e["source"] as? String, text: e["text"] as? String, at: at)
        }
        s.reminders = (frame["reminders"] as? [[String: Any]] ?? []).compactMap { r in
            guard let id = r["id"] as? String, let text = (r["text"] as? String) ?? (r["title"] as? String), !text.isEmpty else { return nil }
            let action = r["action"] as? [String: Any]
            return Reminder(id: id, text: String(text.prefix(160)), tone: r["tone"] as? String ?? "info",
                            tab: action.flatMap { $0["kind"] as? String == "open_panel" ? $0["tab"] as? String : nil })
        }
        s.reasons = (frame["reasons"] as? [String] ?? []).prefix(12).map { String($0.prefix(60)) }
        if let h = frame["honesty"] as? [String: Any] { s.snapshotAge = PetJSON.number(h["snapshot_age"]) }
        if let r = frame["reaction"] as? [String: Any] { s.reaction = r["id"] as? String }
        return s
    }

    var stateLabel: String { PetCatalog.label(state) }
    var info: PetStateInfo? { PetCatalog.info(state) }

    /// "Codex · 5 小时 还剩 82% · 2时31分 · 2 个会话进行中": the same line the pet says when poked, and nothing
    /// that is not known (an unreadable quota is "not known", never 0%).
    func summaryLine(now: Date = Date()) -> String {
        var parts: [String] = []
        if energy.known, let remaining = energy.remaining {
            parts.append("\(energy.label ?? "额度") 还剩 \(Fmt.percent(remaining.rounded()))")
            if let reset = energy.resetsAt { parts.append(Fmt.shortCountdown(to: reset, now: now, past: "待刷新")) }
        } else if energy.stale {
            parts.append("额度数据已过期，我也不确定")
        } else {
            parts.append("还没读到百分比额度")
        }
        if running > 0 { parts.append("\(running) 个会话进行中") }
        return parts.joined(separator: " · ")
    }

    /// Readable versions of the brain's `reasons`, for the "判断依据" line. Unknown codes are shown as they are.
    var explanation: [String] {
        reasons.compactMap { Self.gloss($0) }
    }

    static func gloss(_ reason: String) -> String? {
        if reason.hasPrefix("idle>="), reason.hasSuffix("m"), let minutes = Int(reason.dropFirst(6).dropLast()) { return "已经 \(minutes) 分钟没有活动" }
        let parts = reason.split(separator: "=", maxSplits: 1).map(String.init)
        let key = parts[0], value = parts.count > 1 ? parts[1] : ""
        switch key {
        case "state", "preview", "demo": return nil
        case "activity.running": return "\(value) 个会话在运行"
        case "images.generating": return "\(value) 张图片在生成"
        case "waiting": return "\(appName(value)) 在等你"
        case "backend": return "连不上本机后端"
        case "quiet_hours": return "免打扰时段"
        case "reminder.within_24h": return "24 小时内有到期提醒"
        case "forecast": return value == "resetting" ? "重置预测：快重置了" : "重置预测：有戏"
        case "quota": return "额度数据已过期"
        case "energy":
            // "low(15)" -> "额度偏低（15%）"
            let tone = value.split(separator: "(").first.map(String.init) ?? value
            let number = value.split(separator: "(").dropFirst().first.map { $0.replacingOccurrences(of: ")", with: "") }
            let word = ["ok": "额度充足", "low": "额度偏低", "critical": "额度告急", "empty": "额度用完"][tone] ?? "额度 \(tone)"
            return number.map { "\(word)（\($0)%）" } ?? word
        default: return reason
        }
    }

    private static func appName(_ id: String) -> String {
        ["claude": "Claude", "codex": "Codex", "kimi": "Kimi", "agent": "Agent"][id] ?? id
    }
}
