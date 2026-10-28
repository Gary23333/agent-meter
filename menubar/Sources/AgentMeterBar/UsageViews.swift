import Charts
import SwiftUI

enum Period: String, CaseIterable, Identifiable {
    case today, week = "7d", month = "30d", all
    var id: String { rawValue }
    var label: String {
        switch self {
        case .today: return "今日"
        case .week: return "7 天"
        case .month: return "30 天"
        case .all: return "全部"
        }
    }
}

/// Local token history across every ledger: what was consumed, by which app and model.
struct UsageView: View {
    let snapshot: Snapshot
    let now: Date
    @AppStorage("usagePeriod") private var periodRaw = Period.today.rawValue

    private var period: Period { Period(rawValue: periodRaw) ?? .today }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                PillTabs(items: Period.allCases, title: { $0.label },
                         selection: Binding(get: { period }, set: { periodRaw = $0.rawValue }), small: true)
                IconButton(symbol: "square.and.arrow.up", help: "生成用量报告与分享图") {
                    ReportWindow.show()
                }
            }

            if let data = LocalUsage.merged(snapshot: snapshot, period: period) {
                PeriodSummary(data: data, history: snapshot.history, snapshot: snapshot, now: now)
            } else {
                Card {
                    Label(Catalog.reason(snapshot.history?.reason ?? "database_not_found"), systemImage: "tray")
                        .font(.system(size: 12)).themeForeground(.secondary)
                }
            }
        }
    }
}

private struct Segment: Identifiable {
    let id: String
    let label: String
    let value: Double
    let color: Color
}

private struct PeriodSummary: View {
    let data: JSON
    let history: Source?
    let snapshot: Snapshot
    let now: Date
    @Environment(\.panelTheme) private var theme

    private var totals: JSON { data["totals"] }
    private var segments: [Segment] {
        [Segment(id: "in", label: "新输入", value: totals["fresh_input"].double ?? 0, color: theme.series(Color(red: 0.30, green: 0.56, blue: 0.98), index: 0)),
         Segment(id: "out", label: "输出", value: totals["output"].double ?? 0, color: theme.series(Color(red: 0.58, green: 0.40, blue: 0.97), index: 1)),
         Segment(id: "cr", label: "缓存读取", value: totals["cache_read"].double ?? 0, color: theme.series(Color(red: 0.22, green: 0.76, blue: 0.70), index: 2)),
         Segment(id: "cw", label: "缓存写入", value: totals["cache_write"].double ?? 0, color: theme.series(Color(red: 0.98, green: 0.64, blue: 0.24), index: 3))]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            hero
            PeakPricingCard(data: data, now: now)
            composition
            byApp
            topModels
            footnote
        }
    }

    private var hero: some View {
        let total = totals["total_tokens"].double ?? 0
        let cost = headlineCost
        return HStack(alignment: .top, spacing: 10) {
            Card(tint: Color(red: 0.36, green: 0.52, blue: 1)) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("TOKEN 总量").font(theme.font(10.5, weight: .semibold)).themeForeground(.secondary).kerning(0.35)
                    HStack(alignment: .firstTextBaseline, spacing: 3) {
                        Text(Fmt.tokens(total)).font(theme.number(27)).monospacedDigit()
                            .themeForeground()
                            .contentTransition(.numericText())
                        if data["total_is_lower_bound"].bool == true {
                            Text("起").font(theme.font(11, weight: .semibold)).foregroundStyle(.orange)
                                .help("部分历史已被汇总为日数据，总量为下界")
                        }
                    }
                    Text("\(Fmt.grouped(totals["requests"].double ?? 0)) 次请求")
                        .font(theme.font(10.5, weight: .medium)).themeForeground(.tertiary)
                }
                .frame(minHeight: 78, alignment: .topLeading)
            }
            Card(tint: Color(red: 0.15, green: 0.82, blue: 0.62)) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("估算费用").font(theme.font(10.5, weight: .semibold)).themeForeground(.secondary).kerning(0.35)
                    Text(cost.map { Fmt.amount($0.amount, unit: $0.unit) } ?? "—")
                        .font(theme.number(27)).monospacedDigit()
                        .themeForeground()
                        .contentTransition(.numericText())
                    Text(costComposition).font(theme.font(10.5, weight: .medium)).themeForeground(.tertiary)
                        .lineLimit(2).fixedSize(horizontal: false, vertical: true)
                    if let note = unpricedNote {
                        Text(note).font(theme.font(10.5, weight: .medium)).foregroundStyle(.orange)
                            .lineLimit(2).fixedSize(horizontal: false, vertical: true)
                            .help("这些模型在本地价格表里没有匹配条目，未计入估算；可在「API 价格表（本机估算）…」里补充")
                    }
                }
                .frame(minHeight: 78, alignment: .topLeading)
            }
            .help("按 API 价格估算，不是订阅账单")
        }
    }

    /// One headline figure: CC Switch's own USD estimate plus the price-table
    /// estimate when that table is in USD. A CNY table is never folded into a
    /// USD number — the composition line lists both separately. An all-zero
    /// result stays "—": unknown prices are not zero cost.
    private var headlineCost: (amount: Double, unit: String)? {
        let local = data["local_cost"].object
        let cc = totals["estimated_cost_usd"].double ?? 0
        let localUSD = local["USD"]?.double ?? 0
        if cc > 0 || localUSD > 0 { return (cc + localUSD, "USD") }
        if let cny = local["CNY"]?.double, cny > 0 { return (cny, "CNY") }
        return nil
    }

    /// Where the estimate comes from, per source and per currency. Zero
    /// parts stay off the line ("价格表 $0" reads like a bug, not a total).
    private var costComposition: String {
        let cc = totals["estimated_cost_usd"].double
        var parts: [String] = []
        if let cc, cc > 0 { parts.append("CC Switch " + Fmt.usd(cc)) }
        for (unit, value) in data["local_cost"].object.sorted(by: { $0.key < $1.key }) {
            let amount = value.double ?? 0
            if amount > 0 { parts.append("价格表 " + Fmt.amount(amount, unit: unit)) }
        }
        let n = Int(totals["unpriced_detail_requests"].double ?? 0)
        if n > 0 { parts.append("\(n) 次无定价") }
        return parts.isEmpty ? "API 等价估算" : parts.joined(separator: " · ")
    }

    /// Models the price table could not cost, so the number is a lower bound.
    private var unpricedNote: String? {
        let names = data["unpriced_models"].array.compactMap { $0.string }
        guard !names.isEmpty else { return nil }
        return "未计价模型：" + names.prefix(4).joined(separator: "、")
            + (names.count > 4 ? " 等 \(names.count) 个" : "")
    }

    /// Donut of input / output / cache, cache hit rate in the middle.
    private var composition: some View {
        let parts = segments.filter { $0.value > 0 }
        return Card {
            SectionTitle(text: "构成", trailing: "输入 / 输出 / 缓存")
            HStack(spacing: 18) {
                ZStack {
                    Chart(parts) { s in
                        SectorMark(angle: .value("Token", s.value), innerRadius: .ratio(0.70), angularInset: 1.2)
                            .cornerRadius(2.5)
                            .foregroundStyle(s.color.gradient)
                    }
                    .frame(width: 100, height: 100)
                    .themeGlow(segments[2].color.opacity(0.24), radius: 5, theme: theme)
                    VStack(spacing: 1) {
                        Text(totals["cache_hit_rate"].double.map { Fmt.percent(($0 * 1000).rounded() / 10) } ?? "—")
                            .font(theme.number(17)).monospacedDigit().themeForeground()
                        Text("缓存命中").font(theme.font(9, weight: .medium)).themeForeground(.tertiary)
                    }
                }
                .frame(width: 104, height: 104)
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(segments) { s in
                        HStack(spacing: 7) {
                            RoundedRectangle(cornerRadius: 2).fill(s.color.gradient).frame(width: 8, height: 8)
                            Text(s.label).font(theme.font(11, weight: .medium)).themeForeground(.secondary)
                            Spacer(minLength: 8)
                            Text(Fmt.tokens(s.value))
                                .font(.system(size: 11.5, weight: .semibold, design: theme.numberDesign))
                                .monospacedDigit().themeForeground()
                                .frame(width: 64, alignment: .trailing)
                        }
                    }
                }
                .frame(maxWidth: .infinity)
            }
        }
    }

    private struct AppTotal: Identifiable {
        let id: String
        var tokens: Double
        var requests: Double
        var costs: [String: Double]
    }

    private var appTotals: [AppTotal] {
        var map: [String: AppTotal] = [:]
        for g in data["groups"].array {
            let app = g["app"].string ?? "其他"
            var t = map[app] ?? AppTotal(id: app, tokens: 0, requests: 0, costs: [:])
            t.tokens += g["total_tokens"].double ?? 0
            t.requests += g["requests"].double ?? 0
            for (unit, amount) in groupCost(g) { t.costs[unit, default: 0] += amount }
            map[app] = t
        }
        return map.values.sorted { $0.tokens > $1.tokens }
    }

    @ViewBuilder private var byApp: some View {
        let apps = appTotals
        if !apps.isEmpty {
            let top = apps.first?.tokens ?? 1
            Card {
                SectionTitle(text: "按应用", trailing: "\(apps.count) 个来源")
                ForEach(apps) { a in
                    VStack(alignment: .leading, spacing: 5) {
                        HStack(spacing: 6) {
                            // CC Switch app keys map to discovery providers ("mcode" → minimax_code).
                            let provider = a.id == "mcode" ? "minimax_code" : a.id
                            if let icon = AppLauncher.icon(for: provider, in: snapshot) {
                                Image(nsImage: icon).resizable().frame(width: 16, height: 16)
                            } else {
                                Circle().fill(theme.tint(Catalog.appTint(a.id))).frame(width: 7, height: 7)
                            }
                            Text(Catalog.appLabel(a.id)).font(theme.font(12, weight: .medium)).themeForeground().lineLimit(1)
                            OpenAppButton(sourceID: provider, snapshot: snapshot, compact: true)
                            Spacer(minLength: 4)
                            Text(Fmt.tokens(a.tokens))
                                .font(.system(size: 12, weight: .semibold, design: theme.numberDesign))
                                .monospacedDigit().themeForeground().frame(width: 64, alignment: .trailing)
                            Text(costLabel(a.costs)).font(theme.font(10.5, weight: .medium)).themeForeground(.secondary).monospacedDigit()
                                .frame(width: 56, alignment: .trailing)
                        }
                        Meter(fraction: a.tokens / max(top, 1), tint: theme.tint(Catalog.appTint(a.id)), height: 5)
                    }
                }
            }
        }
    }

    private struct ModelRow: Identifiable {
        let id: String
        var label: String
        var app: String
        var tokens: Double
        var costs: [String: Double]
    }

    /// Model ranking inside one app: the same model spelled differently
    /// ("glm-5.3-flash" vs "glm-5-3-flash") is one row.
    private var modelRows: [ModelRow] {
        var map: [String: ModelRow] = [:]
        for g in data["groups"].array {
            let raw = g["model"].string ?? "未知模型"
            let app = g["app"].string ?? ""
            let key = app + "\u{1}" + Catalog.modelKey(raw)
            var row = map[key] ?? ModelRow(id: key, label: Catalog.modelLabel(raw), app: app, tokens: 0, costs: [:])
            row.tokens += g["total_tokens"].double ?? 0
            for (unit, amount) in groupCost(g) { row.costs[unit, default: 0] += amount }
            map[key] = row
        }
        return map.values.sorted { $0.tokens > $1.tokens }
    }

    /// What one token group costs: CC Switch prices each of its own groups;
    /// local sources get a per-model amount from the price-table estimate.
    private func groupCost(_ g: JSON) -> [String: Double] {
        if let usd = g["estimated_cost_usd"].double, usd > 0 { return ["USD": usd] }
        let entry = data["cost_index"][g["source"].string ?? ""]
        guard let unit = entry["unit"].string,
              let amount = entry["models"][g["model"].string ?? ""].double, amount > 0 else { return [:] }
        return [unit: amount]
    }

    private func costLabel(_ costs: [String: Double]) -> String {
        guard !costs.isEmpty else { return "—" }
        return costs.sorted { $0.key < $1.key }.map { Fmt.amount($0.value, unit: $0.key) }.joined(separator: " + ")
    }

    @ViewBuilder private var topModels: some View {
        let groups = Array(modelRows.prefix(5))
        if !groups.isEmpty {
            Card {
                SectionTitle(text: "模型排行", trailing: "Top \(groups.count)")
                ForEach(groups) { g in
                    HStack(spacing: 6) {
                        Text(g.label).font(theme.font(11.5, weight: .medium)).themeForeground()
                            .lineLimit(1).truncationMode(.middle).layoutPriority(1)
                        Text(Catalog.appLabel(g.app))
                            .font(theme.font(9, weight: .semibold))
                            .padding(.horizontal, 5).padding(.vertical, 2)
                            .foregroundStyle(theme.tint(Catalog.appTint(g.app)))
                            .background(Capsule().fill(theme.tint(Catalog.appTint(g.app)).opacity(theme == .minimal ? 0.07 : 0.12)))
                        Spacer(minLength: 4)
                        Text(costLabel(g.costs)).font(theme.font(10.5, weight: .medium)).themeForeground(.secondary)
                            .monospacedDigit().frame(width: 56, alignment: .trailing)
                        Text(Fmt.tokens(g.tokens))
                            .font(.system(size: 11.5, weight: .semibold, design: theme.numberDesign))
                            .monospacedDigit().themeForeground().frame(width: 62, alignment: .trailing)
                    }
                    .frame(minHeight: 21)
                }
            }
        }
    }

    /// Which local ledgers were summed in, for the footnote.
    private var sourceNote: String {
        let extra = data["includes_local"].array.compactMap { $0.string }
        guard !extra.isEmpty else { return "数据来自 CC Switch 本机记录" }
        return "数据来自 CC Switch 与 " + extra.map { Catalog.brand($0).name }.joined(separator: "、") + " 本机记录"
    }

    private var footnote: some View {
        var parts = [sourceNote]
        if let imported = history?.lastImport { parts.append("最近导入 " + Fmt.ago(imported, now: now)) }
        if data["period_status"].string == "partial" { parts.append("部分日期仅有日汇总") }
        return Text(parts.joined(separator: " · "))
            .font(.system(size: 10)).themeForeground(.tertiary)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 2)
    }
}


/// Peak / off-peak split for the current period: DeepSeek prices requests
/// inside its discount window differently, and ledgers without request
/// timestamps were estimated entirely at the off-peak rate.
private struct PeakPricingCard: View {
    let data: JSON
    let now: Date
    @Environment(\.panelTheme) private var theme

    private var peakTokens: Double { data["totals"]["peak_tokens"].double ?? 0 }
    private var offpeakTokens: Double { data["totals"]["offpeak_tokens"].double ?? 0 }

    private var intervals: [(start: Int, end: Int)] {
        let parsed = data["peak_window"]["intervals"].array.compactMap { pair -> (Int, Int)? in
            let values = pair.array
            guard values.count == 2, let s = minutes(values[0].string ?? ""),
                  let e = minutes(values[1].string ?? "") else { return nil }
            return (s, e)
        }
        return parsed.isEmpty ? [(9 * 60, 12 * 60), (14 * 60, 18 * 60)] : parsed
    }

    private var windowNote: String {
        data["peak_window"]["note"].string ?? "工作日 09:00–12:00、14:00–18:00 峰时；其余与周末谷时"
    }

    private func minutes(_ s: String) -> Int? {
        let parts = s.split(separator: ":")
        guard parts.count == 2, let h = Int(parts[0]), let m = Int(parts[1]) else { return nil }
        return h * 60 + m
    }

    private func clock(_ minutes: Int) -> String {
        String(format: "%02d:%02d", minutes / 60, minutes % 60)
    }

    private var nowMinutes: Int {
        let c = Fmt.calendar.dateComponents([.hour, .minute], from: now)
        return (c.hour ?? 0) * 60 + (c.minute ?? 0)
    }

    /// Weekends are off-peak all day; weekdays are peak inside the intervals.
    private var weekday: Int {
        Fmt.calendar.component(.weekday, from: now)   // 1 = Sunday, 7 = Saturday
    }

    private var isWeekend: Bool {
        weekday == 1 || weekday == 7
    }

    private var isOffPeak: Bool {
        isWeekend || !intervals.contains { nowMinutes >= $0.start && nowMinutes < $0.end }
    }

    private var hint: String {
        if isWeekend { return "周末全天谷时" }
        if isOffPeak {
            if let next = intervals.map(\.start).first(where: { $0 > nowMinutes }) {
                return "\(clock(next)) 进入峰时"
            }
            // Friday evening's next peak day is Monday, not tomorrow.
            let prefix = weekday == 6 ? "周一 " : "明日 "
            return prefix + "\(clock(intervals.first?.start ?? 9 * 60)) 进入峰时"
        }
        if let current = intervals.first(where: { nowMinutes >= $0.start && nowMinutes < $0.end }) {
            return "\(clock(current.end)) 结束"
        }
        return ""
    }

    private var statusColor: Color {
        isOffPeak ? Color(red: 0.10, green: 0.66, blue: 0.52) : (theme.isLuminous ? Neon.orange : .orange)
    }

    private func costs(_ key: String) -> [String: Double] {
        data[key].object.compactMapValues { $0.double }
    }

    var body: some View {
        let peak = peakTokens
        let offpeak = offpeakTokens
        let split = peak + offpeak
        let share = split > 0 ? offpeak / split : 0
        let unsplit = data["peak_unsplit"].array.compactMap { $0.string }
        return Card {
            HStack(spacing: 6) {
                Text("峰谷定价").font(theme.font(11.5, weight: .semibold)).themeForeground(.secondary)
                Spacer(minLength: 8)
                Text(isOffPeak ? "谷时" : "峰时")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(statusColor)
                    .padding(.horizontal, 7).padding(.vertical, 3)
                    .background(Capsule().fill(statusColor.opacity(0.13)))
                    .overlay(Capsule().strokeBorder(statusColor.opacity(0.30), lineWidth: 0.5))
                Text(hint).font(.system(size: 9.5)).themeForeground(.tertiary)
            }
            Text("\(windowNote)；DeepSeek 系模型峰时 ×2，其余模型不分峰谷")
                .font(.system(size: 10.5)).themeForeground(.tertiary)
            splitRow("峰时", tokens: peak, amounts: costs("local_peak_cost"))
            splitRow("谷时", tokens: offpeak, amounts: costs("local_offpeak_cost"))
            if split > 0 {
                VStack(alignment: .leading, spacing: 4) {
                    Meter(fraction: share, tint: Color(red: 0.15, green: 0.82, blue: 0.62), height: 5)
                    HStack(spacing: 6) {
                        Text("谷时 Token 占比 " + Fmt.percent((share * 1000).rounded() / 10))
                            .font(.system(size: 10)).themeForeground(.tertiary).monospacedDigit()
                        Spacer(minLength: 6)
                        Text("已拆分 \(Fmt.tokens(split)) / \(Fmt.tokens(data["totals"]["total_tokens"].double ?? split))")
                            .font(.system(size: 9.5)).themeForeground(.tertiary).monospacedDigit()
                    }
                }
            } else {
                Text("当前账本没有可拆分的请求时刻")
                    .font(.system(size: 10.5)).themeForeground(.tertiary)
            }
            if !unsplit.isEmpty {
                Text("未拆分来源按谷价计入价格表估算：" + unsplit.map { Catalog.brand($0).name }.joined(separator: "、"))
                    .font(.system(size: 10)).foregroundStyle(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text("CC Switch 自带估价不分峰谷，未计入上面的价格表金额")
                    .font(.system(size: 9.5)).themeForeground(.tertiary)
            }
        }
    }

    private func splitRow(_ title: String, tokens: Double, amounts: [String: Double]) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(title).font(theme.font(11.5, weight: .medium)).themeForeground(.secondary)
                .frame(width: theme == .minimal ? 34 : 40, alignment: .leading)
            Text(Fmt.tokens(tokens))
                .font(.system(size: 12.5, weight: .semibold, design: theme.numberDesign))
                .monospacedDigit().themeForeground()
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 1) {
                if amounts.isEmpty {
                    Text("—").font(.system(size: 11.5, weight: .medium, design: theme.numberDesign))
                        .themeForeground(.tertiary)
                } else {
                    ForEach(amounts.keys.sorted(), id: \.self) { unit in
                        Text(Fmt.amount(amounts[unit] ?? 0, unit: unit))
                            .font(.system(size: 11.5, weight: .semibold, design: theme.numberDesign))
                            .monospacedDigit().themeForeground()
                    }
                }
            }
        }
    }
}

/// One local-usage view summing every local token ledger: CC Switch's imports
/// plus the direct readers (Kimi Code, ZCode, OpenCode, WorkBuddy, and the
/// Codex / Claude Code / Gemini / MiniMax Code session logs). They record
/// different clients — or, for the CLIs CC Switch also imports, only the days
/// it never imported — so the sum has no double counting, and the tab works
/// on machines without CC Switch at all.
enum LocalUsage {
    /// Per-app totals from the same merged chain the usage tab renders, so an
    /// account card's token rows can never disagree with the tab. Keys are the
    /// group app names; callers map provider ids ("minimax_code" → "mcode").
    static func appTotals(_ snapshot: Snapshot, period: Period) -> [String: (tokens: Double, requests: Double)] {
        guard let data = merged(snapshot: snapshot, period: period) else { return [:] }
        var map: [String: (tokens: Double, requests: Double)] = [:]
        for g in data["groups"].array {
            let app = g["app"].string ?? "其他"
            map[app, default: (0, 0)].tokens += g["total_tokens"].double ?? 0
            map[app, default: (0, 0)].requests += g["requests"].double ?? 0
        }
        return map
    }

    static func merged(snapshot: Snapshot, period: Period) -> JSON? {
        var base: JSON?
        var totals: [String: JSON] = ["requests": .number(0), "fresh_input": .number(0), "output": .number(0),
                                      "cache_read": .number(0), "cache_write": .number(0), "total_tokens": .number(0)]
        var groups: [JSON] = []
        var included: [String] = []
        var extraRequests = 0.0
        for source in snapshot.sources {
            guard let value = source.metric("tokens")?.value["periods"][period.rawValue], !value.isNull else { continue }
            if source.id.hasPrefix("codexbar:") { continue }
            if source.id == "ccswitch" { base = value }
            let t = value["totals"]
            for key in totals.keys {
                totals[key] = .number((totals[key]?.double ?? 0) + (t[key].double ?? 0))
            }
            // Each group keeps the source it came from: CC Switch prices its own
            // groups, the local sources are priced per model by the price table.
            for g in value["groups"].array {
                var o = g.object
                o["source"] = .string(source.id)
                groups.append(.object(o))
            }
            if source.id != "ccswitch" {
                included.append(source.baseID)
                extraRequests += t["requests"].double ?? 0
            }
        }
        guard base != nil || !included.isEmpty else { return nil }
        // CC Switch's own USD estimate is part of this view's total, not a
        // separate number; local price-table amounts are kept per currency.
        if let b = base {
            if let cc = b["totals"]["estimated_cost_usd"].double, cc > 0 {
                totals["estimated_cost_usd"] = .number(cc)
            }
            if let n = b["totals"]["unpriced_detail_requests"].double, n > 0 {
                totals["unpriced_detail_requests"] = .number(n)
            }
        }
        var localCosts: [String: Double] = [:]
        var localPeakCosts: [String: Double] = [:]
        var localOffpeakCosts: [String: Double] = [:]
        var costIndex: [String: JSON] = [:]
        var unmatched: [String: Set<String>] = [:]
        for source in snapshot.sources {
            guard let cost = source.metric("cost")?.value, cost["basis"].string == "local_price_table" else { continue }
            let window = cost["periods"][period.rawValue]
            if let unit = cost["unit"].string, let amount = window["amount"].double {
                localCosts[unit, default: 0] += amount
            }
            if let unit = cost["unit"].string {
                if let amount = window["peak_amount"].double { localPeakCosts[unit, default: 0] += amount }
                if let amount = window["offpeak_amount"].double { localOffpeakCosts[unit, default: 0] += amount }
            }
            let models = window["models"].object
            if !models.isEmpty {
                costIndex[source.id] = .object(["unit": cost["unit"], "models": .object(models)])
            }
            unmatched[source.id] = Set(window["unmatched_models"].array.compactMap { $0.string }
                .map { $0.replacingOccurrences(of: " (no breakdown)", with: "") }
                .filter { !$0.isEmpty && $0 != "unknown" })
        }
        // Name the unpriced models by how much they actually consumed.
        var unpriced: [String: Double] = [:]
        for g in groups {
            guard let source = g["source"].string, let model = g["model"].string,
                  unmatched[source]?.contains(model) == true else { continue }
            unpriced[Catalog.modelLabel(model), default: 0] += g["total_tokens"].double ?? 0
        }
        // Peak / off-peak split. Tokens come from the merged groups (each
        // ledger's own peak objects); a ledger with per-model groups but no
        // request-time split was estimated entirely at the off-peak price.
        var peakTokens = 0.0
        var offpeakTokens = 0.0
        for g in groups {
            peakTokens += g["peak"]["total_tokens"].double ?? 0
            offpeakTokens += g["offpeak"]["total_tokens"].double ?? 0
        }
        var peakUnsplit: [String] = []
        var peakWindow: JSON = .null
        for source in snapshot.sources {
            guard let value = source.metric("tokens")?.value["periods"][period.rawValue], !value.isNull else { continue }
            let sourceGroups = value["groups"].array
            if !sourceGroups.isEmpty, !sourceGroups.contains(where: { $0["peak"]["total_tokens"].double != nil }),
               source.metric("cost")?.value["basis"].string == "local_price_table",
               !peakUnsplit.contains(source.id) {
                peakUnsplit.append(source.id)
            }
            if peakWindow.isNull, let w = source.metric("cost")?.value["peak_window"], !w.isNull {
                peakWindow = w
            }
        }
        let fresh = totals["fresh_input"]?.double ?? 0
        let read = totals["cache_read"]?.double ?? 0
        let write = totals["cache_write"]?.double ?? 0
        totals["cache_hit_rate"] = fresh + read + write > 0 ? .number(read / (fresh + read + write)) : .null
        totals["unpriced_extra_requests"] = .number(extraRequests)
        totals["peak_tokens"] = .number(peakTokens)
        totals["offpeak_tokens"] = .number(offpeakTokens)
        var out: [String: JSON] = ["totals": .object(totals), "groups": .array(groups),
                                   "includes_local": .array(included.map { .string($0) })]
        out["local_cost"] = .object(localCosts.mapValues { .number($0) })
        out["local_peak_cost"] = .object(localPeakCosts.mapValues { .number($0) })
        out["local_offpeak_cost"] = .object(localOffpeakCosts.mapValues { .number($0) })
        out["peak_unsplit"] = .array(peakUnsplit.map { .string($0) })
        out["peak_window"] = peakWindow.isNull
            ? .object(["timezone": .string("Asia/Shanghai"),
                       "weekdays": .array([1, 2, 3, 4, 5].map { .number(Double($0)) }),
                       "intervals": .array([["09:00", "12:00"], ["14:00", "18:00"]].map { pair in
                           .array(pair.map { .string($0) })
                       }),
                       "weekend_offpeak": .bool(true),
                       "note": .string("工作日 09:00–12:00、14:00–18:00 峰时；其余与周末全天谷时")])
            : peakWindow
        out["cost_index"] = .object(costIndex)
        out["unpriced_models"] = .array(unpriced.sorted { $0.value > $1.value }.prefix(8).map { .string($0.key) })
        if let periodStatus = base?["period_status"], !periodStatus.isNull {
            out["period_status"] = periodStatus
        }
        return .object(out)
    }
}
