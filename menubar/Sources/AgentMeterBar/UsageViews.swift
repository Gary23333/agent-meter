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

/// Local token history from CC Switch: what was consumed, by which app and model.
struct UsageView: View {
    let snapshot: Snapshot
    let now: Date
    @AppStorage("usagePeriod") private var periodRaw = Period.today.rawValue

    private var period: Period { Period(rawValue: periodRaw) ?? .today }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            PillTabs(items: Period.allCases, title: { $0.label },
                     selection: Binding(get: { period }, set: { periodRaw = $0.rawValue }), small: true)

            if let history = snapshot.history, let data = history.metric("tokens")?.value["periods"][period.rawValue], !data.isNull {
                PeriodSummary(data: LocalUsage.merged(ccswitch: data, snapshot: snapshot, period: period),
                              history: history, snapshot: snapshot, now: now)
            } else {
                Card {
                    Label(Catalog.reason(snapshot.history?.reason ?? "database_not_found"), systemImage: "tray")
                        .font(.system(size: 12)).foregroundStyle(.secondary)
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
    let history: Source
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
            composition
            byApp
            topModels
            footnote
        }
    }

    private var hero: some View {
        let total = totals["total_tokens"].double ?? 0
        let cost = totals["estimated_cost_usd"].double
        return HStack(alignment: .top, spacing: 10) {
            Card(tint: Color(red: 0.36, green: 0.52, blue: 1)) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Token 总量").font(.system(size: 11)).foregroundStyle(.secondary)
                    HStack(alignment: .firstTextBaseline, spacing: 3) {
                        Text(Fmt.tokens(total)).font(theme.number(26)).monospacedDigit()
                            .foregroundStyle(theme.figure([Color(red: 0.45, green: 0.6, blue: 1), Color(red: 0.75, green: 0.45, blue: 1)]))
                            .themeGlow(Neon.cyan.opacity(0.6), radius: 4, theme: theme == .neon ? .neon : .minimal)
                            .contentTransition(.numericText())
                        if data["total_is_lower_bound"].bool == true {
                            Text("起").font(.system(size: 11, weight: .semibold)).foregroundStyle(.orange)
                                .help("部分历史已被汇总为日数据，总量为下界")
                        }
                    }
                    Text("\(Fmt.grouped(totals["requests"].double ?? 0)) 次请求")
                        .font(.system(size: 10.5)).foregroundStyle(.secondary)
                }
            }
            Card(tint: Color(red: 0.15, green: 0.82, blue: 0.62)) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("估算费用").font(.system(size: 11)).foregroundStyle(.secondary)
                    Text(cost.map(Fmt.usd) ?? "—").font(theme.number(26)).monospacedDigit()
                        .foregroundStyle(theme == .neon ? AnyShapeStyle(LinearGradient(colors: [Neon.lime, Neon.cyan], startPoint: .leading, endPoint: .trailing))
                                                        : theme.figure([Color(red: 0.2, green: 0.9, blue: 0.6), Color(red: 0.2, green: 0.75, blue: 1)]))
                        .themeGlow(Neon.lime.opacity(0.6), radius: 4, theme: theme == .neon ? .neon : .minimal)
                        .contentTransition(.numericText())
                    Text(unpricedNote).font(.system(size: 10.5)).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            .help("按 API 价格估算，不是订阅账单")
        }
    }

    private var unpricedNote: String {
        let n = Int(totals["unpriced_detail_requests"].double ?? 0)
        var parts = [n > 0 ? "API 等价 · \(n) 次无定价" : "API 等价估算"]
        if data["includes_kimi"].bool == true { parts.append("不含 Kimi") }
        return parts.joined(separator: " · ")
    }

    /// Donut of input / output / cache, cache hit rate in the middle.
    private var composition: some View {
        let parts = segments.filter { $0.value > 0 }
        return Card {
            Text("构成").font(.system(size: 12, weight: .semibold))
            HStack(spacing: 16) {
                ZStack {
                    Chart(parts) { s in
                        SectorMark(angle: .value("Token", s.value), innerRadius: .ratio(0.68), angularInset: 1.5)
                            .cornerRadius(3)
                            .foregroundStyle(s.color.gradient)
                    }
                    .frame(width: 104, height: 104)
                    .themeGlow(segments[2].color.opacity(0.45), radius: 8, theme: theme)
                    VStack(spacing: 0) {
                        Text(totals["cache_hit_rate"].double.map { Fmt.percent(($0 * 1000).rounded() / 10) } ?? "—")
                            .font(theme.number(16)).monospacedDigit()
                            .foregroundStyle(segments[2].color)
                        Text("缓存命中").font(.system(size: 9)).foregroundStyle(.secondary)
                    }
                }
                VStack(alignment: .leading, spacing: 7) {
                    ForEach(segments) { s in
                        HStack(spacing: 6) {
                            RoundedRectangle(cornerRadius: 2).fill(s.color.gradient).frame(width: 8, height: 8)
                                .themeGlow(s.color, radius: 2, theme: theme)
                            Text(s.label).font(.system(size: 11)).foregroundStyle(.secondary)
                            Spacer(minLength: 2)
                            Text(Fmt.tokens(s.value)).font(.system(size: 11.5, weight: theme == .minimal ? .regular : .bold, design: theme.numberDesign)).monospacedDigit()
                        }
                    }
                }
            }
        }
    }

    private struct AppTotal: Identifiable {
        let id: String
        var tokens: Double
        var cost: Double
        var requests: Double
        var priced: Bool
    }

    private var appTotals: [AppTotal] {
        var map: [String: AppTotal] = [:]
        for g in data["groups"].array {
            let app = g["app"].string ?? "其他"
            var t = map[app] ?? AppTotal(id: app, tokens: 0, cost: 0, requests: 0, priced: false)
            t.tokens += g["total_tokens"].double ?? 0
            if let c = g["estimated_cost_usd"].double { t.cost += c; t.priced = true }
            t.requests += g["requests"].double ?? 0
            map[app] = t
        }
        return map.values.sorted { $0.tokens > $1.tokens }
    }

    @ViewBuilder private var byApp: some View {
        let apps = appTotals
        if !apps.isEmpty {
            let top = apps.first?.tokens ?? 1
            Card {
                Text("按应用").font(.system(size: 12, weight: .semibold))
                ForEach(apps) { a in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            // CC Switch app keys map to discovery providers ("mcode" → minimax_code).
                            let provider = a.id == "mcode" ? "minimax_code" : a.id
                            if let icon = AppLauncher.icon(for: provider, in: snapshot) {
                                Image(nsImage: icon).resizable().frame(width: 16, height: 16)
                            } else {
                                Circle().fill(theme.tint(Catalog.appTint(a.id))).frame(width: 7, height: 7).themeGlow(Catalog.appTint(a.id), radius: 3, theme: theme)
                            }
                            Text(Catalog.appLabel(a.id)).font(.system(size: 12, weight: .medium))
                            OpenAppButton(sourceID: provider, snapshot: snapshot, compact: true)
                            Spacer()
                            Text(Fmt.tokens(a.tokens)).font(.system(size: 12, weight: .semibold)).monospacedDigit()
                            Text(a.priced ? Fmt.usd(a.cost) : "—").font(.system(size: 11)).foregroundStyle(.secondary).monospacedDigit()
                                .frame(minWidth: 54, alignment: .trailing)
                        }
                        Meter(fraction: a.tokens / max(top, 1), tint: theme.tint(Catalog.appTint(a.id)), height: 5)
                    }
                }
            }
        }
    }

    @ViewBuilder private var topModels: some View {
        let groups = data["groups"].array.sorted { ($0["total_tokens"].double ?? 0) > ($1["total_tokens"].double ?? 0) }.prefix(5)
        if !groups.isEmpty {
            Card {
                Text("模型 Top \(groups.count)").font(.system(size: 12, weight: .medium))
                ForEach(Array(groups.enumerated()), id: \.offset) { _, g in
                    HStack(spacing: 8) {
                        Text(g["model"].string ?? "未知模型").font(.system(size: 11.5)).lineLimit(1).truncationMode(.middle)
                        Text(Catalog.appLabel(g["app"].string ?? ""))
                            .font(.system(size: 9.5, weight: .medium))
                            .padding(.horizontal, 5).padding(.vertical, 1)
                            .foregroundStyle(theme.tint(Catalog.appTint(g["app"].string ?? "")))
                            .background(Capsule().fill(theme.tint(Catalog.appTint(g["app"].string ?? "")).opacity(theme == .minimal ? 0.06 : 0.13)))
                        Spacer()
                        Text(Fmt.tokens(g["total_tokens"].double ?? 0)).font(.system(size: 11.5, weight: .medium)).monospacedDigit()
                    }
                }
            }
        }
    }

    private var footnote: some View {
        var parts = [data["includes_kimi"].bool == true ? "数据来自 CC Switch 与 Kimi Code 本机记录" : "数据来自 CC Switch 本机记录"]
        if let imported = history.lastImport { parts.append("最近导入 " + Fmt.ago(imported, now: now)) }
        if data["period_status"].string == "partial" { parts.append("部分日期仅有日汇总") }
        return Text(parts.joined(separator: " · "))
            .font(.system(size: 10)).foregroundStyle(.tertiary)
            .padding(.horizontal, 2)
    }
}


/// One local-usage view: CC Switch history plus Kimi Code's own session logs.
/// They record different clients (CC Switch's "kimi-for-coding" rows are
/// Claude Code routed to Kimi, not the Kimi Code app), so the sum has no overlap.
enum LocalUsage {
    static func merged(ccswitch data: JSON, snapshot: Snapshot, period: Period) -> JSON {
        guard let kimi = snapshot.sources.first(where: { $0.id == "kimi" })?.metric("tokens")?.value["periods"][period.rawValue],
              !kimi.isNull else { return data }
        let a = data["totals"], b = kimi["totals"]
        func sum(_ key: String) -> Double { (a[key].double ?? 0) + (b[key].double ?? 0) }
        var totals = a.object
        for key in ["requests", "fresh_input", "output", "cache_read", "cache_write", "total_tokens"] {
            totals[key] = .number(sum(key))
        }
        let base = sum("fresh_input") + sum("cache_read") + sum("cache_write")
        totals["cache_hit_rate"] = base > 0 ? .number(sum("cache_read") / base) : .null
        totals["unpriced_extra_requests"] = .number(b["requests"].double ?? 0)
        var out = data.object
        out["totals"] = .object(totals)
        out["groups"] = .array(data["groups"].array + kimi["groups"].array)
        out["includes_kimi"] = .bool(true)
        return .object(out)
    }
}
