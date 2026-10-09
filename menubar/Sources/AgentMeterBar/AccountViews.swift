import Charts
import SwiftUI

struct AccountsView: View {
    let snapshot: Snapshot
    let now: Date

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if snapshot.accountSources.isEmpty {
                Card {
                    Text("暂时没有可显示的账户额度。").font(.system(size: 12)).foregroundStyle(.secondary)
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
                Text(Catalog.reason(source.reason)).font(.system(size: 10.5)).foregroundStyle(.secondary)
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

    private var brand: Catalog.Brand { Catalog.brand(source.id) }
    private var quotas: [JSON] { source.metric("quota")?.value.rows.filter { $0["remaining_percent"].double != nil } ?? [] }

    var body: some View {
        Card(tint: brand.tint) {
            header
            if quotas.count == 1 { singleQuota(quotas[0]) }
            else if quotas.count > 1 { VStack(spacing: 9) { ForEach(quotas.indices, id: \.self) { QuotaBar(quota: quotas[$0], now: now) } } }
            details
            dailyTokens
        }
    }

    /// Account-side daily tokens (Codex), last 30 recorded days.
    @ViewBuilder private var dailyTokens: some View {
        let points: [(day: Date, tokens: Double)] = (source.metric("tokens")?.value["daily_buckets"].array ?? [])
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
                        .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    Spacer()
                    Text(Fmt.tokens(points.reduce(0) { $0 + $1.tokens }))
                        .font(.system(size: 11, weight: .bold, design: .rounded)).foregroundStyle(brand.tint)
                }
                Chart {
                    ForEach(points, id: \.day) { p in
                        AreaMark(x: .value("日期", p.day), y: .value("Token", p.tokens))
                            .foregroundStyle(LinearGradient(colors: [brand.tint.opacity(0.45), brand.tint.opacity(0.02)],
                                                            startPoint: .top, endPoint: .bottom))
                            .interpolationMethod(.catmullRom)
                        LineMark(x: .value("日期", p.day), y: .value("Token", p.tokens))
                            .foregroundStyle(brand.tint)
                            .lineStyle(StrokeStyle(lineWidth: 1.6, lineCap: .round))
                            .interpolationMethod(.catmullRom)
                    }
                }
                .chartXAxis(.hidden)
                .chartYAxis(.hidden)
                .frame(height: 40)
                .shadow(color: brand.tint.opacity(0.5), radius: 4)
            }
        }
    }

    private var header: some View {
        HStack(spacing: 10) {
            BrandBadge(brand: brand, size: 30, icon: AppLauncher.icon(for: source.baseID, in: snapshot))
            VStack(alignment: .leading, spacing: 1) {
                Text(source.displayName).font(.system(size: 13.5, weight: .bold))
                Text(subtitle).font(.system(size: 10.5)).foregroundStyle(.secondary).lineLimit(1)
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

    private func singleQuota(_ q: JSON) -> some View {
        let remaining = q["remaining_percent"].double ?? 0
        return HStack(spacing: 14) {
            Ring(remaining: remaining, size: 70, lineWidth: 7)
            VStack(alignment: .leading, spacing: 5) {
                Text("\(Catalog.bucketLabel(q)) 窗口").font(.system(size: 12, weight: .medium))
                if let used = q["used_percent"].double {
                    Text("已用 \(Fmt.percent(used.rounded()))").font(.system(size: 11)).foregroundStyle(.secondary)
                }
                if let reset = q["resets_at"].date {
                    HStack(spacing: 4) {
                        Image(systemName: "arrow.clockwise").font(.system(size: 9.5, weight: .semibold))
                        Text(reset > now ? "\(Fmt.countdown(to: reset, now: now)) 重置" : "已重置，待刷新")
                    }
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(brand.tint)
                    Text(Fmt.moment(reset, now: now)).font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
                }
            }
            Spacer(minLength: 0)
        }
    }

    @ViewBuilder private var details: some View {
        let rows = detailRows
        if !rows.isEmpty {
            VStack(spacing: 7) {
                ForEach(rows.indices, id: \.self) { rows[$0] }
            }
            .padding(.top, quotas.isEmpty ? 0 : 2)
        }
        let cards = source.metric("reset_cards")?.value["cards"].array ?? []
        if !cards.isEmpty {
            ResetCardStrip(cards: cards, now: now, tint: brand.tint)
        }
    }

    private var detailRows: [InfoRow] {
        var rows: [InfoRow] = []
        if let cards = source.metric("reset_cards")?.value {
            let count = Int(cards["available_count"].double ?? 0)
            let expiries = cards["cards"].array.compactMap { $0["expires_at"].date }.filter { $0 > now }.sorted()
            let next = expiries.first ?? cards["next_known_expiry"].date
            rows.append(InfoRow(symbol: "ticket", title: "重置卡", value: "\(count) 张",
                                detail: next.map { "最早 \(Fmt.moment($0, now: now)) 到期" }))
        }
        for c in source.metric("credits")?.value.rows ?? [] {
            rows.append(contentsOf: creditRows(c))
        }
        if let v = source.metric("credit_refresh_time")?.value, let day = Fmt.parseDay(v["date"].string) {
            rows.append(InfoRow(symbol: "arrow.triangle.2.circlepath", title: "积分更新", value: Fmt.dayCountdown(day, now: now),
                                detail: Fmt.day(day, now: now) + (v["origin"].string == "user" ? " · 手填" : ""),
                                valueTint: brand.tint))
        }
        if let v = source.metric("renewal_time")?.value, let day = Fmt.parseDay(v["date"].string) {
            var detail = Fmt.day(day, now: now)
            if let a = source.metric("renewal_amount")?.value, let amount = a["amount"].double {
                detail += " · " + Fmt.amount(amount, unit: a["currency"].string)
                if a["confirmed_by_provider"].bool == false { detail += "（手填）" }
            }
            rows.append(InfoRow(symbol: "calendar", title: "续费", value: Fmt.dayCountdown(day, now: now), detail: detail))
        } else if let end = Fmt.parseDay(source.subscription["ends_on"].string) {
            let note = source.subscription["auto_renew"].bool == false ? "未开自动续费" : nil
            rows.append(InfoRow(symbol: "calendar", title: "会员到期", value: Fmt.dayCountdown(end, now: now),
                                detail: [Fmt.day(end, now: now), note].compactMap { $0 }.joined(separator: " · ")))
        }
        if let t = source.metric("tokens")?.value["lifetime_tokens"].double, t > 0 {
            rows.append(InfoRow(symbol: "number", title: "账户累计 Token", value: Fmt.tokens(t)))
        }
        // Local session history (Kimi Code): today / 30 days / all.
        if let periods = source.metric("tokens")?.value["periods"], !periods.isNull {
            let today = periods["today"]["totals"], month = periods["30d"]["totals"], all = periods["all"]["totals"]
            rows.append(InfoRow(symbol: "number", title: "本机 Token 今日", value: Fmt.tokens(today["total_tokens"].double ?? 0),
                                detail: "\(Int(today["requests"].double ?? 0)) 轮" + (today["cache_hit_rate"].double.map { " · 缓存命中 " + Fmt.percent(($0 * 1000).rounded() / 10) } ?? "")))
            rows.append(InfoRow(symbol: "calendar.badge.clock", title: "近 30 天 / 全部", value: Fmt.tokens(month["total_tokens"].double ?? 0),
                                detail: "全部 " + Fmt.tokens(all["total_tokens"].double ?? 0)))
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
                                valueTint: .secondary))
        }
        return rows
    }
}

struct QuotaBar: View {
    let quota: JSON
    let now: Date
    var body: some View {
        let remaining = quota["remaining_percent"].double ?? 0
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(Catalog.bucketLabel(quota)).font(.system(size: 12, weight: .medium))
                if let used = quota["used"].double, let limit = quota["limit"].double {
                    Text("\(Fmt.trim(used))/\(Fmt.trim(limit))").font(.system(size: 10.5)).foregroundStyle(.tertiary).monospacedDigit()
                }
                Spacer()
                Text("剩余 \(Fmt.percent(remaining.rounded()))")
                    .font(.system(size: 12, weight: .semibold)).monospacedDigit()
                    .foregroundStyle(healthTint(remaining))
            }
            Meter(fraction: remaining / 100, tint: healthTint(remaining), accent: healthTintAccent(remaining))
            if let reset = quota["resets_at"].date {
                Text("\(reset > now ? Fmt.countdown(to: reset, now: now) + " 重置" : "已重置，待刷新") · \(Fmt.moment(reset, now: now))")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
            }
        }
    }
}

/// One chip per reset card, coloured by how soon it expires.
struct ResetCardStrip: View {
    let cards: [JSON]
    let now: Date
    let tint: Color
    var body: some View {
        HStack(spacing: 6) {
            ForEach(cards.indices, id: \.self) { i in
                let exp = cards[i]["expires_at"].date
                let days = exp.map { Int($0.timeIntervalSince(now) / 86400) }
                let urgent = (days ?? 99) < 7
                VStack(alignment: .leading, spacing: 1) {
                    Text("第 \(i + 1) 张").font(.system(size: 9.5)).foregroundStyle(.secondary)
                    Text(exp.map { Fmt.day($0, now: now) } ?? "未知").font(.system(size: 11, weight: .semibold)).monospacedDigit()
                    Text(days.map { $0 >= 0 ? "\($0) 天后到期" : "已到期" } ?? "").font(.system(size: 9.5))
                        .foregroundStyle(urgent ? Color.orange : Color.secondary)
                }
                .padding(.horizontal, 8).padding(.vertical, 6)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(tint.opacity(urgent ? 0.06 : 0.1)))
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).strokeBorder(urgent ? Color.orange.opacity(0.5) : tint.opacity(0.25), lineWidth: 0.6))
            }
        }
    }
}
