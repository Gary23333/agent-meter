import Charts
import SwiftUI

struct AccountsView: View {
    let snapshot: Snapshot
    let now: Date

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if snapshot.accountSources.isEmpty {
                Card {
                    Text("暂时没有可显示的账户额度。").font(.system(size: 12)).themeForeground(.secondary)
                }
            }
            ForEach(snapshot.accountSources) { AccountCard(source: $0, snapshot: snapshot, now: now) }
            if !snapshot.inactiveSources.isEmpty {
                SectionTitle(text: "未接入").padding(.top, 4)
                Card {
                    ForEach(Array(snapshot.inactiveSources.enumerated()), id: \.element.id) { i, s in
                        if i > 0 { Divider().opacity(0.5) }
                        InactiveRow(source: s, snapshot: snapshot)
                    }
                }
            }
        }
    }
}

struct InactiveRow: View {
    let source: Source
    let snapshot: Snapshot
    var body: some View {
        let brand = Catalog.brand(source.id)
        HStack(spacing: 10) {
            BrandBadge(brand: brand, size: 22, icon: AppLauncher.icon(for: source.baseID, in: snapshot)).saturation(0.35).opacity(0.85)
            VStack(alignment: .leading, spacing: 1) {
                Text(source.displayName).font(.system(size: 12, weight: .medium))
                Text(Catalog.reason(source.reason)).font(.system(size: 10.5)).themeForeground(.secondary)
            }
            Spacer()
            OpenAppButton(sourceID: source.baseID, snapshot: snapshot, compact: true)
            if WebProvider.isAPIKeyProvider(source.baseID) {
                Button(source.reason?.hasSuffix("credential_not_connected") == true ? "填写密钥" : "更换密钥") {
                    ConnectionManager.shared.showConnections()
                }
                .controlSize(.small)
            } else if source.reason == "disabled_by_user" {
                StatusPill(status: source.status, text: "已关闭")
            } else if WebProvider.find(source.baseID) != nil {
                Button(ConnectionManager.shared.isConnected(source.id) ? "重新登录" : "登录") { ConnectionManager.shared.login(sourceID: source.id) }
                    .controlSize(.small)
            } else {
                StatusPill(status: source.status)
            }
        }
    }
}

struct AccountCard: View {
    let source: Source
    let snapshot: Snapshot
    let now: Date
    @Environment(\.panelTheme) private var theme

    private var brand: Catalog.Brand { Catalog.brand(source.id) }
    /// Brand colour as the current theme shows it.
    private var tint: Color { theme.tint(brand.tint) }
    private var quotas: [JSON] { Catalog.sortedQuotas(source.metric("quota")?.value.rows.filter { $0["remaining_percent"].double != nil } ?? []) }

    var body: some View {
        Card(tint: brand.tint) {
            // Same section order for every provider: quota windows, balances,
            // credit refresh, reset cards, renewal, tokens.
            header
            if !quotas.isEmpty { VStack(spacing: 9) { ForEach(quotas.indices, id: \.self) { QuotaBar(quota: quotas[$0], now: now) } } }
            details
            webUsage
            deepseekPeak
            dailyTokens
            imageTrend
        }
    }

    /// DeepSeek's peak / off-peak pricing belongs on its own account card; the
    /// numbers still come from the local ledgers, not the platform console.
    @ViewBuilder private var deepseekPeak: some View {
        if source.baseID == "deepseek_api" {
            DeepSeekPeakSection(snapshot: snapshot, now: now).padding(.top, 2)
        }
    }

    /// DeepSeek platform console usage: shown beside the local ledger, never
    /// summed into local consumption. Windows are the backend's precomputed
    /// 3-day / 7-day sums; without them the daily rows are summed in Beijing
    /// calendar days here.
    @ViewBuilder private var webUsage: some View {
        if let cost = source.metric("cost")?.value, cost["basis"].string == "platform_web_usage" {
            let unit = cost["currency"].string
            let windows = webWindows(cost)
            let bars = webBars(cost)
            VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 6) {
                    Text("网页消耗").font(theme.font(11.5, weight: .semibold)).themeForeground(.secondary)
                    Spacer(minLength: 6)
                    Text("网页端数据，不计入本机消耗").font(.system(size: 9.5)).themeForeground(.tertiary)
                }
                HStack(spacing: 7) {
                    ForEach(windows) { w in
                        WebUsageTile(title: w.title, amount: w.amount, tokens: w.tokens, requests: w.requests,
                                     unit: unit, tint: tint)
                    }
                }
                if !bars.isEmpty {
                    HStack(spacing: 6) {
                        Text("近 7 日金额").font(.system(size: 9.5)).themeForeground(.tertiary)
                        Spacer(minLength: 6)
                        Text(Fmt.amount(bars.reduce(0) { $0 + $1.amount }, unit: unit))
                            .font(.system(size: 10, weight: .semibold, design: theme.numberDesign))
                            .monospacedDigit().themeForeground(.secondary)
                    }
                    Chart {
                        ForEach(bars, id: \.day) { b in
                            BarMark(x: .value("日期", b.day), y: .value("金额", b.amount), width: .fixed(10))
                                .foregroundStyle(tint.gradient)
                                .cornerRadius(2)
                        }
                    }
                    .chartXAxis(.hidden)
                    .chartYAxis(.hidden)
                    .frame(height: 40)
                    .themeGlow(tint.opacity(0.35), radius: 3, theme: theme)
                }
            }
            .padding(.top, quotas.isEmpty ? 0 : 2)
        }
    }

    private struct WebWindow: Identifiable {
        let id: String
        let title: String
        let amount: Double
        let tokens: Double
        let requests: Double
    }

    private func webWindows(_ cost: JSON) -> [WebWindow] {
        let specs = [("today", "今日", 1), ("3d", "近 3 天", 3), ("7d", "近 7 天", 7)]
        return specs.map { key, title, days in
            let w = cost["windows"][key]
            if !w.isNull, w["amount"].double != nil || w["tokens"].double != nil || w["requests"].double != nil {
                return WebWindow(id: key, title: title,
                                 amount: w["amount"].double ?? 0,
                                 tokens: w["tokens"].double ?? 0,
                                 requests: w["requests"].double ?? 0)
            }
            let fallback = sumWebDays(cost, days: days)
            return WebWindow(id: key, title: title, amount: fallback.amount,
                             tokens: fallback.tokens, requests: fallback.requests)
        }
    }

    /// Sums the daily rows over the last `days` Beijing calendar days.
    private func sumWebDays(_ cost: JSON, days: Int) -> (amount: Double, tokens: Double, requests: Double) {
        let start = Fmt.calendar.date(byAdding: .day, value: -(days - 1), to: Fmt.calendar.startOfDay(for: now))
        var amount = 0.0, tokens = 0.0, requests = 0.0
        for row in cost["daily"].array {
            guard let day = Fmt.parseDay(row["date"].string) else { continue }
            if let start, day < start { continue }
            amount += row["amount"].double ?? 0
            tokens += row["tokens"].double ?? 0
            requests += row["requests"].double ?? 0
        }
        return (amount, tokens, requests)
    }

    /// Last seven dated rows that actually cost something; an all-zero
    /// platform history has no shape worth charting.
    private func webBars(_ cost: JSON) -> [(day: Date, amount: Double)] {
        cost["daily"].array
            .compactMap { row -> (date: Date, amount: Double)? in
                guard let day = Fmt.parseDay(row["date"].string), let amount = row["amount"].double else { return nil }
                return amount > 0 ? (day, amount) : nil
            }
            .sorted { $0.date < $1.date }
            .suffix(7)
            .map { (day: $0.date, amount: $0.amount) }
    }

    /// Account-side daily tokens (Codex), last 30 recorded days.
    @ViewBuilder private var dailyTokens: some View {
        // The rows above use the merged chain, which carries no per-app daily
        // series. A ledger whose days CC Switch also imported is partial here
        // (missing days would read as zero-usage gaps), so only an
        // overlap-free ledger is charted.
        let overlap = source.metric("tokens")?.value["ccswitch_overlap"]["excluded_days"].array ?? []
        let buckets = overlap.isEmpty ? source.metric("tokens")?.value["daily_buckets"].array ?? [] : []
        let points: [(day: Date, tokens: Double)] = buckets
            .compactMap { b in
                guard let d = Fmt.parseDay(b["date"].string), let t = b["tokens"].double else { return nil }
                return (d, t)
            }
            .sorted { $0.day < $1.day }
            .suffix(30)
        if points.count >= 3 {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("近 \(points.count) 个活跃日 · \(source.metric("tokens")?.value["coverage"].string == "kimi_code_local_sessions" ? "本机" : "账户") Token")
                        .font(.system(size: 10.5)).themeForeground(.secondary)
                    Spacer()
                    Text(Fmt.tokens(points.reduce(0) { $0 + $1.tokens }))
                        .font(.system(size: 11, weight: .bold, design: theme.numberDesign)).foregroundStyle(tint)
                }
                Chart {
                    ForEach(points, id: \.day) { p in
                        AreaMark(x: .value("日期", p.day), y: .value("Token", p.tokens))
                            .foregroundStyle(LinearGradient(colors: [tint.opacity(theme == .minimal ? 0.12 : 0.45), tint.opacity(0.02)],
                                                            startPoint: .top, endPoint: .bottom))
                            .interpolationMethod(.catmullRom)
                        LineMark(x: .value("日期", p.day), y: .value("Token", p.tokens))
                            .foregroundStyle(tint)
                            .lineStyle(StrokeStyle(lineWidth: theme == .minimal ? 1 : 1.6, lineCap: .round))
                            .interpolationMethod(.catmullRom)
                    }
                }
                .chartXAxis(.hidden)
                .chartYAxis(.hidden)
                .frame(height: 40)
                .themeGlow(tint.opacity(0.5), radius: 4, theme: theme)
            }
        }
    }

    /// Codex's built-in image_gen archive: daily image counts, last 30 active days.
    @ViewBuilder private var imageTrend: some View {
        if source.id == "codex", let metric = source.metric("image_generation") {
            let points: [(day: Date, images: Double)] = metric.value["daily_buckets"].array
                .compactMap { b in
                    guard let d = Fmt.parseDay(b["date"].string), let n = b["images"].double, n > 0 else { return nil }
                    return (d, n)
                }
                .sorted { $0.day < $1.day }
                .suffix(30)
            let monthImages = metric.value["periods"]["30d"]["images"].double
                ?? points.reduce(0) { $0 + $1.images }
            if !points.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text("近 \(points.count) 个活跃日 · 生图")
                            .font(.system(size: 10.5)).themeForeground(.secondary)
                        Spacer()
                        Text("\(Int(monthImages)) 张")
                            .font(.system(size: 11, weight: .bold, design: theme.numberDesign)).foregroundStyle(tint)
                    }
                    Chart {
                        ForEach(points, id: \.day) { p in
                            BarMark(x: .value("日期", p.day), y: .value("张数", p.images), width: .fixed(8))
                                .foregroundStyle(tint.gradient)
                                .cornerRadius(2)
                        }
                    }
                    .chartXAxis(.hidden)
                    .chartYAxis(.hidden)
                    .frame(height: 40)
                    .themeGlow(tint.opacity(0.4), radius: 4, theme: theme)
                }
            }
        }
    }

    private var header: some View {
        HStack(spacing: 10) {
            BrandBadge(brand: brand, size: 30, icon: AppLauncher.icon(for: source.baseID, in: snapshot))
            VStack(alignment: .leading, spacing: 1) {
                Text(source.displayName).font(.system(size: 13.5, weight: theme == .minimal ? .semibold : .bold))
                Text(subtitle).font(.system(size: 10.5)).themeForeground(.secondary).lineLimit(1)
            }
            Spacer()
            if source.status != "available" {
                StatusPill(status: source.status)
                    .help(source.lastError.map { "最近一次读取失败：" + Catalog.reason($0) } ?? Catalog.reason(source.reason))
            }
            OpenAppButton(sourceID: source.baseID, snapshot: snapshot)
        }
    }

    private var subtitle: String {
        var parts: [String] = []
        if let plan = source.subscription["plan"].string { parts.append(plan) }
        else { parts.append(Catalog.scopeLabel(source.scope)) }
        if source.status == "stale", let t = source.observedAt { parts.append("采样于 " + Fmt.moment(t, now: now)) }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder private var details: some View {
        let top = balanceRows
        let bottom = renewalAndTokenRows
        let cards = source.metric("reset_cards")?.value["cards"].array ?? []
        if !top.isEmpty || !bottom.isEmpty || resetCardRow != nil {
            VStack(spacing: 7) {
                ForEach(top.indices, id: \.self) { top[$0] }
                if let row = resetCardRow {
                    row
                    if !cards.isEmpty { ResetCardStrip(cards: cards, now: now, tint: tint).padding(.bottom, 2) }
                }
                ForEach(bottom.indices, id: \.self) { bottom[$0] }
            }
            .padding(.top, quotas.isEmpty ? 0 : 2)
        }
    }

    /// Countdowns are coloured by urgency, never by brand, so every card agrees.
    private func dueTint(_ day: Date) -> Color {
        let d = Fmt.daysUntil(day, now: now)
        if d <= 3 { return theme == .neon ? Neon.orange : .orange }
        return .primary
    }

    private var resetCardRow: InfoRow? {
        guard let cards = source.metric("reset_cards")?.value else { return nil }
        let count = Int(cards["available_count"].double ?? 0)
        let expiries = cards["cards"].array.compactMap { $0["expires_at"].date }.filter { $0 > now }.sorted()
        let next = expiries.first ?? cards["next_known_expiry"].date
        return InfoRow(symbol: "ticket", title: "重置卡", value: "\(count) 张",
                       detail: next.map { "最早 \(Fmt.moment($0, now: now)) 到期" })
    }

    /// Balances and credit buckets, then when credits next refresh.
    private var balanceRows: [InfoRow] {
        var rows: [InfoRow] = []
        for c in source.metric("credits")?.creditRows ?? [] {
            rows.append(contentsOf: creditRows(c))
        }
        if let v = source.metric("credit_refresh_time")?.value, let day = Fmt.parseDay(v["date"].string) {
            rows.append(InfoRow(symbol: "arrow.triangle.2.circlepath", title: "积分更新", value: Fmt.dayCountdown(day, now: now),
                                detail: Fmt.day(day, now: now) + (v["origin"].string == "user" ? " · 手填" : ""),
                                valueTint: dueTint(day)))
        }
        return rows
    }

    private var renewalAndTokenRows: [InfoRow] {
        var rows: [InfoRow] = []
        if let v = source.metric("renewal_time")?.value, let day = Fmt.parseDay(v["date"].string) {
            var detail = Fmt.day(day, now: now)
            if let a = source.metric("renewal_amount")?.value, let amount = a["amount"].double {
                detail += " · " + Fmt.amount(amount, unit: a["currency"].string)
                if a["confirmed_by_provider"].bool == false { detail += "（手填）" }
            }
            rows.append(InfoRow(symbol: "calendar", title: "续费", value: Fmt.dayCountdown(day, now: now), detail: detail,
                                valueTint: dueTint(day)))
        } else if let end = Fmt.parseDay(source.subscription["ends_on"].string) {
            let note = source.subscription["auto_renew"].bool == false ? "未开自动续费" : nil
            rows.append(InfoRow(symbol: "calendar", title: "会员到期", value: Fmt.dayCountdown(end, now: now),
                                detail: [Fmt.day(end, now: now), note].compactMap { $0 }.joined(separator: " · "),
                                valueTint: dueTint(end)))
        }
        if let t = source.metric("tokens")?.value["lifetime_tokens"].double, t > 0 {
            rows.append(InfoRow(symbol: "number", title: "账户累计 Token", value: Fmt.tokens(t)))
        }
        // DeepSeek console usage: display-only, never part of local consumption.
        if let usage = source.metric("cost")?.value, usage["basis"].string == "platform_web_usage" {
            rows.append(InfoRow(symbol: "chart.bar.doc.horizontal", title: "近 30 天消耗",
                                value: Fmt.amount(usage["total_amount"].double ?? 0, unit: usage["currency"].string),
                                detail: Fmt.tokens(usage["total_tokens"].double ?? 0) + " token",
                                valueTint: brand.tint))
        }
        // Local token history: the same merged chain the usage tab sums (CC
        // Switch imports plus the direct readers, with the overlap between
        // them already excluded), attributed per app. Reading a provider's own
        // ledger here would show 0 for every day CC Switch imported.
        let appKey = source.baseID == "minimax_code" ? "mcode" : source.baseID
        let today = LocalUsage.appTotals(snapshot, period: .today)[appKey]
        let month = LocalUsage.appTotals(snapshot, period: .month)[appKey]
        let all = LocalUsage.appTotals(snapshot, period: .all)[appKey]
        if today != nil || month != nil || all != nil {
            rows.append(InfoRow(symbol: "number", title: "本机 Token 今日", value: Fmt.tokens(today?.tokens ?? 0),
                                detail: "\(Int(today?.requests ?? 0)) 轮"))
            rows.append(InfoRow(symbol: "calendar.badge.clock", title: "近 30 天 / 全部", value: Fmt.tokens(month?.tokens ?? 0),
                                detail: "全部 " + Fmt.tokens(all?.tokens ?? 0)))
        }
        // Codex built-in image_gen: display-only API-equivalent estimate, never
        // part of the token/cost totals above.
        if source.id == "codex", let metric = source.metric("image_generation"),
           let images = metric.value["periods"]["today"]["images"].double {
            var detail: [String] = []
            if let cost = metric.value["periods"]["today"]["estimated_cost"].double {
                detail.append("约 " + Fmt.amount(cost, unit: metric.value["currency"].string))
            }
            if let monthly = metric.value["periods"]["30d"]["images"].double {
                detail.append("近 30 天 \(Int(monthly)) 张")
            }
            rows.append(InfoRow(symbol: "photo.on.rectangle.angled", title: "生图 今日",
                                value: "\(Int(images)) 张",
                                detail: detail.isEmpty ? nil : detail.joined(separator: " · ")))
        }
        // Qoder CN local credits ledger (its logs carry credits, never token
        // counts): account-card statistics only, never local consumption.
        if let usage = source.metric("credits")?.value["usage"], !usage.isNull, !usage["periods"].isNull {
            let periods = usage["periods"]
            let today = periods["today"]["totals"], month = periods["30d"]["totals"], all = periods["all"]["totals"]
            rows.append(InfoRow(symbol: "circle.hexagongrid.fill", title: "积分消耗 今日",
                                value: Fmt.grouped(Fmt.credits(today["credits"])),
                                detail: "\(Int(today["requests"].double ?? 0)) 次请求 · 计费 " + Fmt.grouped(Fmt.credits(today["billable_credits"]))))
            rows.append(InfoRow(symbol: "calendar.badge.clock", title: "积分 近 30 天 / 全部",
                                value: Fmt.grouped(Fmt.credits(month["credits"])),
                                detail: "全部 " + Fmt.grouped(Fmt.credits(all["credits"])) + " · 本机记录，不计入本机消耗"))
        }
        return rows
    }

    private func creditRows(_ c: JSON) -> [InfoRow] {
        let unit = c["unit"].string
        let raw = c["balance"].double ?? c["remaining"].double ?? c["amount"].double ?? c["total"].double
        if c["unlimited"].bool == true {
            return [InfoRow(symbol: "infinity", title: "余额", value: "无限额度")]
        }
        guard let balance = raw else { return [] }
        let isMoney = unit == "CNY" || unit == "USD"
        let value = isMoney ? Fmt.amount(balance, unit: unit) : Fmt.grouped(balance) + " " + Catalog.unitLabel(unit)
        var title = c["kind"].string == "booster_wallet" ? "加油包余额" : "余额"
        if let b = c["bucket"].string, b != source.id, b != "codex" { title = Catalog.bucketLabel(c) }
        var detail: String?
        if let granted = c["granted"].double, let topped = c["topped_up"].double {
            detail = "赠送 \(Fmt.amount(granted, unit: unit)) · 充值 \(Fmt.amount(topped, unit: unit))"
        }
        var rows = [InfoRow(symbol: isMoney ? "creditcard" : "circle.hexagongrid.fill", title: title, value: value, detail: detail)]
        // Credit buckets with their own expiry (e.g. MiniMax Design membership credits).
        for b in c["buckets"].array {
            guard let amount = b["balance"].double else { continue }
            let exp = b["expires_at"].date
            let bucketTitle = ["vip": "会员积分", "gift": "赠送积分", "purchase": "购买积分"][b["type"].string ?? ""] ?? "积分包"
            rows.append(InfoRow(symbol: "hourglass", title: bucketTitle,
                                value: Fmt.grouped(amount),
                                detail: exp.map { "\(Fmt.day($0, now: now)) 失效 · \(Fmt.countdown(to: $0, now: now))" } ?? "无失效日期",
                                valueTint: .secondary, nested: true))
        }
        return rows
    }
}

/// DeepSeek's peak / off-peak split inside its API account card: requests in
/// the discount window cost less, and ledgers without request timestamps were
/// estimated entirely at the off-peak rate. Only DeepSeek models count, so a
/// shared local ledger never leaks other models' tokens into this section.
private struct DeepSeekPeakSection: View {
    let snapshot: Snapshot
    let now: Date
    @AppStorage("usagePeriod") private var periodRaw = Period.today.rawValue
    @Environment(\.panelTheme) private var theme

    private var period: Period { Period(rawValue: periodRaw) ?? .today }
    private var split: LocalUsage.DeepSeekPeak? { LocalUsage.deepseekPeak(snapshot: snapshot, period: period) }
    private var window: JSON { split?.window ?? .null }

    private var intervals: [(start: Int, end: Int)] {
        let parsed = window["intervals"].array.compactMap { pair -> (Int, Int)? in
            let values = pair.array
            guard values.count == 2, let s = minutes(values[0].string ?? ""),
                  let e = minutes(values[1].string ?? "") else { return nil }
            return (s, e)
        }
        return parsed.isEmpty ? [(9 * 60, 12 * 60), (14 * 60, 18 * 60)] : parsed
    }

    private var windowNote: String {
        window["note"].string ?? "工作日 09:00–12:00、14:00–18:00 峰时；其余与周末谷时"
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

    var body: some View {
        if let split = split {
            VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 6) {
                    Text("DeepSeek 峰谷定价").font(theme.font(11.5, weight: .semibold)).themeForeground(.secondary)
                    Spacer(minLength: 8)
                    Text(isOffPeak ? "谷时" : "峰时")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(statusColor)
                        .padding(.horizontal, 7).padding(.vertical, 3)
                        .background(Capsule().fill(statusColor.opacity(0.13)))
                        .overlay(Capsule().strokeBorder(statusColor.opacity(0.30), lineWidth: 0.5))
                    Text(hint).font(.system(size: 9.5)).themeForeground(.tertiary)
                }
                PillTabs(items: Period.allCases, title: { $0.label },
                         selection: Binding(get: { period }, set: { periodRaw = $0.rawValue }), small: true)
                Text("\(windowNote)；DeepSeek 系模型峰时 ×2")
                    .font(.system(size: 10.5)).themeForeground(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
                splitRow("峰时", tokens: split.peakTokens, amounts: split.peakCosts)
                splitRow("谷时", tokens: split.offpeakTokens, amounts: split.offpeakCosts)
                let splitTotal = split.peakTokens + split.offpeakTokens
                if splitTotal > 0 {
                    let share = split.offpeakTokens / splitTotal
                    VStack(alignment: .leading, spacing: 4) {
                        Meter(fraction: share, tint: Color(red: 0.15, green: 0.82, blue: 0.62), height: 5)
                        HStack(spacing: 6) {
                            Text("谷时 Token 占比 " + Fmt.percent((share * 1000).rounded() / 10))
                                .font(.system(size: 10)).themeForeground(.tertiary).monospacedDigit()
                            Spacer(minLength: 6)
                            Text("已拆分 \(Fmt.tokens(splitTotal)) / \(Fmt.tokens(split.totalTokens))")
                                .font(.system(size: 9.5)).themeForeground(.tertiary).monospacedDigit()
                        }
                    }
                } else if split.totalTokens > 0 {
                    Text("该时间段没有可拆分的 DeepSeek 请求时刻")
                        .font(.system(size: 10.5)).themeForeground(.tertiary)
                } else {
                    Text("该时间段没有 DeepSeek 模型的本机记录")
                        .font(.system(size: 10.5)).themeForeground(.tertiary)
                }
                if !split.unsplitSources.isEmpty {
                    Text("未拆分来源按谷价计入价格表估算：" + split.unsplitSources.joined(separator: "、"))
                        .font(.system(size: 10)).foregroundStyle(.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if split.hasUnsplitCCSwitch {
                    Text("CC Switch 自带估价不分峰谷，未计入上面的价格表金额")
                        .font(.system(size: 9.5)).themeForeground(.tertiary)
                }
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

/// One platform web-usage window (today / 3 days / 7 days).
private struct WebUsageTile: View {
    let title: String
    let amount: Double
    let tokens: Double
    let requests: Double
    let unit: String?
    let tint: Color
    @Environment(\.panelTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(theme.font(9.5, weight: .medium)).themeForeground(.secondary)
            Text(Fmt.amount(amount, unit: unit))
                .font(.system(size: 15, weight: .semibold, design: theme.numberDesign))
                .monospacedDigit().foregroundStyle(tint).lineLimit(1)
            Text(Fmt.tokens(tokens) + " token").font(.system(size: 9.5)).themeForeground(.tertiary).lineLimit(1)
            Text(Fmt.grouped(requests) + " 次请求").font(.system(size: 9.5)).themeForeground(.tertiary).lineLimit(1)
        }
        .padding(.horizontal, 8).padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background { tile }
    }

    @ViewBuilder private var tile: some View {
        switch theme {
        case .minimal:
            Rectangle().fill(Color.primary.opacity(0.05))
        case .native:
            RoundedRectangle(cornerRadius: 7, style: .continuous).fill(Color.primary.opacity(0.045))
                .overlay(RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .strokeBorder(Color(nsColor: .separatorColor), lineWidth: 0.5))
        default:
            RoundedRectangle(cornerRadius: 9, style: .continuous).fill(tint.opacity(0.08))
                .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .strokeBorder(tint.opacity(0.20), lineWidth: 0.6))
        }
    }
}

struct QuotaBar: View {
    let quota: JSON
    let now: Date
    @Environment(\.panelTheme) private var theme
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        let remaining = quota["remaining_percent"].double ?? 0
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(Catalog.bucketLabel(quota)).font(theme.font(12, weight: .medium)).themeForeground()
                if let used = quota["used"].double, let limit = quota["limit"].double {
                    let fmt: (Double) -> String = quota["unit"].string == "tokens" ? Fmt.tokens : Fmt.trim
                    Text("\(fmt(used))/\(fmt(limit))").font(theme.font(10.5)).themeForeground(.tertiary).monospacedDigit()
                }
                Spacer(minLength: 8)
                Text("剩余 \(Fmt.percent(remaining.rounded()))")
                    .font(.system(size: 12, weight: .semibold, design: theme.numberDesign)).monospacedDigit()
                    .foregroundStyle(theme.healthText(remaining, scheme: scheme))
            }
            Meter(fraction: remaining / 100, tint: theme.health(remaining), accent: theme.healthAccent(remaining))
            if let reset = quota["resets_at"].date {
                Text("\(reset > now ? Fmt.countdown(to: reset, now: now) + " 重置" : "已重置，待刷新") · \(Fmt.moment(reset, now: now))")
                    .font(theme.font(10.5)).themeForeground(.secondary).monospacedDigit()
            }
        }
    }
}

/// One chip per reset card, coloured by how soon it expires.
struct ResetCardStrip: View {
    let cards: [JSON]
    let now: Date
    let tint: Color
    @Environment(\.panelTheme) private var theme
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        HStack(spacing: 7) {
            ForEach(cards.indices, id: \.self) { i in
                let exp = cards[i]["expires_at"].date
                let days = exp.map { Int($0.timeIntervalSince(now) / 86400) }
                let urgent = (days ?? 99) < 7
                VStack(alignment: .leading, spacing: 2) {
                    Text("第 \(i + 1) 张").font(theme.font(9.5, weight: .medium)).themeForeground(.tertiary)
                    Text(exp.map { Fmt.day($0, now: now) } ?? "未知")
                        .font(.system(size: 11, weight: .semibold, design: theme.numberDesign))
                        .themeForeground().monospacedDigit()
                    Text(days.map { $0 >= 0 ? "\($0) 天后到期" : "已到期" } ?? "")
                        .font(theme.font(9.5, weight: .medium))
                        .foregroundStyle(urgent ? Color.orange : theme.textColor(.secondary, scheme: scheme))
                }
                .padding(.horizontal, 9).padding(.vertical, 7)
                .frame(maxWidth: .infinity, minHeight: 58, alignment: .leading)
                .background { chip(urgent: urgent) }
            }
        }
    }

    @ViewBuilder private func chip(urgent: Bool) -> some View {
        let edge = urgent ? (theme.isLuminous ? Neon.orange : Color.orange) : tint
        switch theme {
        case .minimal:
            Rectangle().fill(urgent ? Color.orange : Color.primary.opacity(0.18)).frame(width: 1)
                .frame(maxWidth: .infinity, alignment: .leading)
        case .native:
            RoundedRectangle(cornerRadius: 7, style: .continuous).fill(Color.primary.opacity(0.045))
                .overlay(RoundedRectangle(cornerRadius: 7, style: .continuous).strokeBorder(urgent ? Color.orange.opacity(0.55) : Color(nsColor: .separatorColor), lineWidth: 0.5))
        case .porcelain, .aurora, .titanium:
            RoundedRectangle(cornerRadius: 9, style: .continuous).fill(tint.opacity(urgent ? 0.07 : 0.10))
                .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous).strokeBorder(urgent ? Color.orange.opacity(0.48) : tint.opacity(0.22), lineWidth: 0.6))
        case .neon, .prism:
            RoundedRectangle(cornerRadius: 6, style: .continuous).fill(edge.opacity(0.08))
                .overlay(RoundedRectangle(cornerRadius: 6, style: .continuous).strokeBorder(edge.opacity(0.48), lineWidth: 0.7))
        }
    }
}
