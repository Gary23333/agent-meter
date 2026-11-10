import AppKit
import SwiftUI

/// One budget alert built from a backend event. The key embeds the backend's
/// stable event id ("budget_daily_exceeded:2026-11-08"), so a collection
/// recovery that back-fills the same day never notifies twice.
struct BudgetAlert: Equatable {
    let key: String
    let title: String
    let body: String
}

/// Parsed GET /v1/budget payload (schema 1). Amounts are local API-equivalent
/// estimates in CNY, never real bills; null spent means unknown, not zero.
struct BudgetStatus: Equatable {
    let json: JSON

    init(_ json: JSON) { self.json = json }

    var isOK: Bool { json["status"].string == "ok" }
    var dailyBudget: Double? { json["daily"]["budget_cny"].double }
    var dailySpent: Double? { json["daily"]["spent_cny"].double }
    var weeklyBudget: Double? { json["weekly"]["budget_cny"].double }
    var weeklySpent: Double? { json["weekly"]["spent_cny"].double }
    var dailyExceeded: Bool { json["daily"]["exceeded"].bool ?? false }
    var dailyPartial: Bool { json["daily"]["partial"].bool ?? false }

    /// The usage tab shows a progress row only when a daily budget is set.
    var showsProgress: Bool { isOK && (dailyBudget ?? 0) > 0 }

    var configDaily: String { json["config"]["daily_cny"].string ?? "" }
    var configWeekly: String { json["config"]["weekly_cny"].string ?? "" }
    var configMultiplier: String { json["config"]["anomaly_multiplier"].string ?? "2.0" }

    /// Pure event → alert mapping; dedup happens against the Notifier's fired
    /// set, exactly like quota alerts.
    var alerts: [BudgetAlert] {
        guard isOK else { return [] }
        return json["events"].array.compactMap { event in
            guard let id = event["id"].string, let kind = event["kind"].string else { return nil }
            let apps = event["top_apps"].array.prefix(2).compactMap { $0["name"].string }.map(Catalog.appLabel)
            let models = event["top_models"].array.prefix(2).compactMap { $0["name"].string }.map(Catalog.modelLabel)
            var scope = ""
            if !apps.isEmpty { scope += "主要应用：" + apps.joined(separator: "、") + "。" }
            if !models.isEmpty { scope += "主要模型：" + models.joined(separator: "、") + "。" }
            let note = "本机 API 等价估算，非实际扣费。"
            func money(_ key: String) -> String { Fmt.amount(event[key].double ?? 0, unit: "CNY") }
            let title: String, body: String
            switch kind {
            case "daily_exceeded":
                title = "今日估算费用已超日预算"
                body = "今日已估算 \(money("spent_cny"))，超出日预算 \(money("budget_cny"))（超 \(money("excess_cny"))）。"
            case "weekly_exceeded":
                title = "本周估算费用已超周预算"
                body = "本自然周已估算 \(money("spent_cny"))，超出周预算 \(money("budget_cny"))（超 \(money("excess_cny"))）。"
            case "anomaly":
                let mult = event["multiplier"].double.map { String(format: "%g", $0) } ?? "2"
                title = "今日消耗速度异常"
                body = "今日已估算 \(money("spent_cny"))（约 \(money("rate_cny_per_hour"))/小时），超过近期日均 \(money("baseline_daily_cny")) 的 \(mult) 倍。"
            default:
                return nil
            }
            return BudgetAlert(key: "budget|" + id, title: title, body: body + scope + note)
        }
    }

    func pendingAlerts(fired: [String: Double]) -> [BudgetAlert] {
        alerts.filter { fired[$0.key] == nil }
    }
}

/// Budget settings window, opened from the panel's settings menu.
@MainActor
enum BudgetWindow {
    private static var window: NSWindow?

    static func show() {
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 460, height: 480),
                             styleMask: [.titled, .closable], backing: .buffered, defer: false)
            w.title = "预算与异常提醒"
            w.isReleasedWhenClosed = false
            w.contentViewController = NSHostingController(rootView: BudgetSettingsView().environment(UsageStore.shared))
            w.center()
            window = w
        }
        StatusBarController.shared.closePanel()
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
        window?.orderFrontRegardless()
    }
}

struct BudgetSettingsView: View {
    @Environment(UsageStore.self) private var store
    @State private var daily = ""
    @State private var weekly = ""
    @State private var multiplier = "2.0"
    @State private var message: String?
    @State private var saving = false
    @State private var loaded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text("预算与异常消耗提醒")
                    .font(.system(size: 17, weight: .semibold, design: .rounded))
                Text("口径为本机 API 等价估算（人民币），与实际扣费无关。时间窗按北京时间自然日 / 自然周（周一开始）；同一事件只提醒一次。")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Form {
                TextField("日预算（元）", text: $daily, prompt: Text("未设置则不提醒"))
                TextField("周预算（元）", text: $weekly, prompt: Text("未设置则不提醒"))
                TextField("异常倍率", text: $multiplier, prompt: Text("2.0"))
                Text("今日消耗速率超过近期日均的该倍数时提醒（今日已过至少 2 小时才判断）。")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
            }
            .formStyle(.grouped)
            if let status = store.budget, status.isOK {
                VStack(alignment: .leading, spacing: 4) {
                    Text("当前进度").font(.system(size: 12, weight: .semibold))
                    progressLine("今日", spent: status.dailySpent, budget: status.dailyBudget)
                    progressLine("本周", spent: status.weeklySpent, budget: status.weeklyBudget)
                }
            }
            HStack {
                if let message {
                    Text(message).font(.system(size: 11)).foregroundStyle(.orange)
                        .lineLimit(2).fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                Button("清除全部预算") { daily = ""; weekly = ""; Task { await save() } }
                    .disabled(saving)
                Button(saving ? "保存中…" : "保存") { Task { await save() } }
                    .buttonStyle(.borderedProminent).disabled(saving)
            }
        }
        .padding(16)
        .frame(width: 460)
        .task { await load() }
    }

    private func progressLine(_ label: String, spent: Double?, budget: Double?) -> some View {
        let spentText = spent.map { Fmt.amount($0, unit: "CNY") } ?? "—"
        let budgetText = budget.map { Fmt.amount($0, unit: "CNY") } ?? "未设置"
        return Text("\(label)：\(spentText) / \(budgetText)")
            .font(.system(size: 11.5)).monospacedDigit().foregroundStyle(.secondary)
    }

    private func load() async {
        guard !loaded, let client = store.backendClient else { return }
        do {
            let status = BudgetStatus(try await client.getBudget())
            daily = status.configDaily
            weekly = status.configWeekly
            multiplier = status.configMultiplier
            loaded = true
        } catch {
            message = "读取预算失败：\(error.localizedDescription)"
        }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            let d = daily.trimmingCharacters(in: .whitespaces)
            let w = weekly.trimmingCharacters(in: .whitespaces)
            let m = multiplier.trimmingCharacters(in: .whitespaces)
            try await store.saveBudget(daily: d.isEmpty ? nil : d,
                                       weekly: w.isEmpty ? nil : w,
                                       multiplier: m.isEmpty ? "2.0" : m)
            message = "已保存。"
        } catch {
            message = "保存失败：\(error.localizedDescription)（金额需为非负数字）"
        }
    }
}

/// One compact line on the local-usage tab: today's estimate vs the budget.
/// Hidden entirely when no daily budget is configured.
struct BudgetProgressRow: View {
    let budget: BudgetStatus
    @Environment(\.panelTheme) private var theme

    var body: some View {
        if budget.showsProgress, let limit = budget.dailyBudget {
            let spent = budget.dailySpent
            let fraction = spent.map { min($0 / limit, 1) } ?? 0
            let tint = budget.dailyExceeded ? Color.orange : theme.accent[0]
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text("今日预算").font(theme.font(10.5, weight: .semibold)).themeForeground(.secondary)
                    Spacer(minLength: 4)
                    Text((spent.map { Fmt.amount($0, unit: "CNY") } ?? "—") + " / " + Fmt.amount(limit, unit: "CNY"))
                        .font(theme.font(11, weight: .semibold)).monospacedDigit()
                        .foregroundStyle(budget.dailyExceeded ? AnyShapeStyle(.orange) : AnyShapeStyle(Color.primary.opacity(0.75)))
                    if budget.dailyPartial {
                        Text("部分").font(theme.font(9.5, weight: .medium)).foregroundStyle(.orange)
                            .help("有来源未计价，金额为已确认部分的下界")
                    }
                }
                Meter(fraction: fraction, tint: tint, height: 5)
            }
            .help("本机 API 等价估算，非实际扣费；北京时间自然日")
        }
    }
}