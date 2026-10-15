import SwiftUI
import AppKit

/// ChatGPT / Codex 全员重置（社区称「Tibo 重置」）预测页。
///
/// 这里只展示第三方追踪站各自的公布值与它们自己的依据，不是本机测量，
/// 也不与各账户自身的 5 小时 / 每周窗口混在一起。
struct ForecastView: View {
    let snapshot: Snapshot
    let now: Date

    var body: some View {
        let source = snapshot.sources.first { $0.id == "reset_forecast" }
        VStack(alignment: .leading, spacing: 12) {
            if let source, let forecast = source.metric("reset_forecast") {
                ForecastHeader(source: source, forecast: forecast.value, now: now)
                if !forecast.value["ensemble"].object.isEmpty {
                    EnsembleCard(ensemble: forecast.value["ensemble"])
                }
                PromiseCard(promises: forecast.value["promises"].array, now: now)
                CountdownCard(targets: source.metric("known_reset_countdown")?.value["targets"].array ?? [], now: now)
                SourcesCard(rows: forecast.value["sources"].array, now: now)
                HistoryCard(events: forecast.value["history_events"].array, now: now)
            } else if let source {
                UnavailableCard(source: source)
            } else {
                Card {
                    SectionTitle(text: "重置预测")
                    Text("后端未返回预测来源，可在设置里确认它没有被禁用。")
                        .font(.system(size: 11.5)).foregroundStyle(.secondary)
                }
            }
        }
    }
}

/// 追踪站自己的枚举值在这里统一成中文口径；未识别的值原样显示，不猜。
enum ForecastCopy {
    static func source(_ id: String?) -> String {
        switch id {
        case "willreset": return "WillReset"
        case "codex_reset": return "Tibo Radar"
        case "codexreset_org": return "Reset Monitor"
        case .some(let id): return id
        default: return "第三方"
        }
    }

    static func confidence(_ value: String?) -> String {
        switch value {
        case "high": return "信心 高"
        case "medium": return "信心 中"
        case "low": return "信心 低"
        case "indirect": return "信心 间接推断"
        case .some(let v): return "信心 \(v)"
        default: return "信心 未报"
        }
    }

    static func calibration(_ state: String?) -> String {
        switch state {
        case "calibrated": return "已校准"
        case "experimental": return "实验性"
        case .some(let v): return v
        default: return "未报"
        }
    }

    static func kind(_ kind: String?) -> String {
        switch kind {
        case "reset": return "重置"
        case "reset_preview", "preview": return "预告"
        case "banked", "credits": return "重置卡"
        case "limits": return "限额"
        case "boost": return "加速"
        case "milestone": return "里程碑"
        case .some(let v): return v
        default: return "事件"
        }
    }

    static func basis(_ basis: String?) -> String {
        basis == "cadence_model_fallback" ? "站内模型值" : "公布值"
    }

    /// The sites' own promise wording, keyed on their published labels.
    static func promise(_ label: String?) -> String {
        switch label {
        case "Explicit future reset, no clock": return "已承诺未来会重置 · 未给时间"
        case "Explicit future reset with a clock": return "已承诺未来会重置 · 给了时间"
        case .some(let v) where !v.isEmpty: return v
        default: return "已承诺未来会重置"
        }
    }
}

// MARK: - Header

private struct ForecastHeader: View {
    let source: Source
    let forecast: JSON
    let now: Date

    var body: some View {
        Card {
            HStack(alignment: .top, spacing: 8) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("全员重置预测").font(.system(size: 13, weight: .semibold))
                    Text(forecast["disclaimer"].string ?? "")
                        .font(.system(size: 10.5)).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 8)
                StatusPill(status: forecast["cache_state"].string == "stale" ? "stale" : source.status)
            }
            HStack(spacing: 10) {
                Label("\(Int(forecast["ensemble"]["n_sources"].double ?? 0)) 家可用",
                      systemImage: "antenna.radiowaves.left.and.right")
                if let at = source.observedAt { Text("抓取 " + Fmt.ago(at, now: now)) }
                Text("每 \(Int(forecast["refresh_minutes"].double ?? 45)) 分钟抓一次")
            }
            .font(.system(size: 10.5)).foregroundStyle(.secondary)
        }
    }
}

// MARK: - Band and weighted median

private struct EnsembleCard: View {
    let ensemble: JSON

    var body: some View {
        let horizons = ensemble["horizons"].object
        Card {
            SectionTitle(text: "下次全员重置概率", trailing: "各站自己公布的数值")
            if horizons.isEmpty {
                Text("没有任何一家给出可用预测。").font(.system(size: 11.5)).foregroundStyle(.secondary)
            }
            ForEach(["24h", "48h"], id: \.self) { key in
                if let band = horizons[key] { BandRow(horizon: key, band: band) }
            }
            Text("区间只由各站公布的数值构成；站内未公布的模型字段不参与合成，只在下方各站口径里列出。")
                .font(.system(size: 10)).foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

private struct BandRow: View {
    let horizon: String
    let band: JSON

    var body: some View {
        let values = band["values"].array
        let low = band["min"].double ?? 0
        let high = band["max"].double ?? 0
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(horizon == "24h" ? "24 小时内" : "48 小时内")
                    .font(.system(size: 11.5)).foregroundStyle(.secondary)
                Spacer()
                Text("\(Fmt.trim(low))–\(Fmt.trim(high))%")
                    .font(.system(size: 13, weight: .bold, design: .rounded)).monospacedDigit()
                Text("中位 \(Fmt.trim(band["weighted_median"].double ?? 0))%")
                    .font(.system(size: 11.5, weight: .medium, design: .rounded))
                    .foregroundStyle(.secondary).monospacedDigit()
                Text(band["agreement"].string == "close" ? "接近" : "分歧")
                    .font(.system(size: 9.5, weight: .semibold))
                    .padding(.horizontal, 5).padding(.vertical, 2)
                    .background(Capsule().fill((band["agreement"].string == "close" ? Color.green : Color.orange).opacity(0.15)))
                    .foregroundStyle(band["agreement"].string == "close" ? Color.green : Color.orange)
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.secondary.opacity(0.16)).frame(height: 5)
                    Capsule()
                        .fill(Color.accentColor.opacity(0.55))
                        .frame(width: max(3, geo.size.width * (high - low) / 100), height: 5)
                        .offset(x: geo.size.width * low / 100)
                    ForEach(Array(values.enumerated()), id: \.offset) { _, item in
                        let pct = item["percent"].double ?? 0
                        Circle().fill(dotTint(item["basis"].string)).frame(width: 7, height: 7)
                            .offset(x: geo.size.width * pct / 100 - 3.5, y: -1)
                    }
                }
            }
            .frame(height: 7)
            HStack(spacing: 8) {
                ForEach(Array(values.enumerated()), id: \.offset) { _, item in
                    let pct = item["percent"].double ?? 0
                    HStack(spacing: 3) {
                        Circle().fill(dotTint(item["basis"].string)).frame(width: 5, height: 5)
                        Text("\(ForecastCopy.source(item["source"].string)) \(Fmt.trim(pct))%")
                            .font(.system(size: 10)).monospacedDigit()
                    }
                    .foregroundStyle(.secondary)
                }
                Spacer()
            }
        }
        .padding(.vertical, 2)
    }

    private func dotTint(_ basis: String?) -> Color {
        basis == "published_answer" ? Color.accentColor : Color.secondary.opacity(0.6)
    }

}

// MARK: - Active promise

/// A promise without a machine-readable clock is a banner, not a countdown.
private struct PromiseCard: View {
    let promises: [JSON]
    let now: Date

    var body: some View {
        if !promises.isEmpty {
            Card(tint: .orange) {
                SectionTitle(text: "站内已挂承诺", trailing: "\(promises.count) 条 · 无兑现时间")
                ForEach(Array(promises.enumerated()), id: \ .offset) { _, item in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            Text(ForecastCopy.source(item["source"].string))
                                .font(.system(size: 11.5, weight: .medium))
                            if let floor = item["floor_percent"].double {
                                Text("该站据此给 \(Fmt.trim(floor))%")
                                    .font(.system(size: 10.5)).foregroundStyle(.orange)
                            }
                            Spacer(minLength: 6)
                            if let at = item["at"].date {
                                Text(Fmt.day(at, now: now) + " " + Fmt.time(at))
                                    .font(.system(size: 10.5, design: .rounded)).monospacedDigit().foregroundStyle(.secondary)
                            }
                        }
                        Text(ForecastCopy.promise(item["label"].string))
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                        if let url = item["url"].string, let quote = item["quote"].string {
                            Button {
                                if let link = URL(string: url) { NSWorkspace.shared.open(link) }
                            } label: {
                                Text("“\(quote)”").font(.system(size: 10.5)).foregroundStyle(.link)
                            }
                            .buttonStyle(.plain)
                            .lineLimit(2)
                        }
                    }
                    .padding(.vertical, 3)
                }
                Text("承诺只说明「会再重置一次」，没给时间时不做倒计时。")
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
            }
        }
    }
}

// MARK: - Known reset countdown

private struct CountdownCard: View {
    let targets: [JSON]
    let now: Date

    var body: some View {
        Card {
            SectionTitle(text: "已知重置倒计时", trailing: targets.isEmpty ? nil : "\(targets.count) 项")
            if targets.isEmpty {
                Text("目前没有可倒计时的目标：各站既没给出带时间的公告，也没有可机读的时段。")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            ForEach(Array(targets.enumerated()), id: \.offset) { _, target in
                CountdownRow(target: target, now: now)
            }
        }
    }
}

private struct CountdownRow: View {
    let target: JSON
    let now: Date

    var body: some View {
        let open = target["open_at"].date
        let close = target["close_at"].date
        let state = target["state"].string ?? "no_clock"
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            VStack(alignment: .leading, spacing: 2) {
                Text(target["label"].string ?? (target["kind"].string ?? ""))
                    .font(.system(size: 12, weight: .medium))
                if let close, target["precision"].string == "window" {
                    Text((open.map { Fmt.moment($0, now: now) + " → " } ?? "") + Fmt.moment(close, now: now) + " 北京时间")
                        .font(.system(size: 10.5)).foregroundStyle(.secondary)
                }
                if let url = target["url"].string, let quote = target["quote"].string {
                    Button {
                        NSWorkspace.shared.open(URL(string: url)!)
                    } label: { Text(quote).font(.system(size: 10)).foregroundStyle(.link) }
                        .buttonStyle(.plain)
                        .lineLimit(2)
                }
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 1) {
                Text(countdownText(state, close: close))
                    .font(.system(size: 12.5, weight: .semibold, design: .rounded)).monospacedDigit()
                    .foregroundStyle(tint(state))
                Text(sourcesBadge(target["sources"].array)).font(.system(size: 9.5)).foregroundStyle(.tertiary)
            }
        }
        .padding(.vertical, 2)
    }

    private func countdownText(_ state: String, close: Date?) -> String {
        switch state {
        case "no_clock": return "未给时间"
        case "label_only": return target["kind"].string == "typical_window" ? "仅文字描述" : "未给时间"
        case "inside_window": return "窗口进行中"
        case "elapsed_awaiting_landing": return "已过 · 等待落地"
        default: return close.map { Fmt.countdown(to: $0, now: now) } ?? "—"
        }
    }

    private func tint(_ state: String) -> Color {
        switch state {
        case "inside_window": return .green
        case "elapsed_awaiting_landing": return .orange
        case "no_clock", "label_only": return .secondary
        default: return .primary
        }
    }

    private func sourcesBadge(_ sources: [JSON]) -> String {
        sources.isEmpty ? "第三方" : sources.compactMap { ForecastCopy.source($0.string) }.joined(separator: " · ")
    }
}

// MARK: - Per source breakdown

private struct SourcesCard: View {
    let rows: [JSON]
    let now: Date

    var body: some View {
        Card {
            SectionTitle(text: "各站口径", trailing: "公布值 / 站内模型值")
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                SourceRow(row: row, now: now)
                if row != rows.last { Divider().opacity(0.4) }
            }
        }
    }
}

private struct SourceRow: View {
    let row: JSON
    let now: Date

    var body: some View {
        let failed = (row["status"].string ?? "") == "error"
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(row["name"].string ?? row["source"].string ?? "")
                    .font(.system(size: 12, weight: .medium))
                if failed {
                    Text(Catalog.reason(row["reason"].string)).font(.system(size: 10.5)).foregroundStyle(.red).lineLimit(2)
                }
                Spacer(minLength: 6)
                if !failed {
                    Text("\(Fmt.trim(row["headline_24h"].double ?? row["raw_24h"].double ?? 0))% / \(Fmt.trim(row["headline_48h"].double ?? row["raw_48h"].double ?? 0))%")
                        .font(.system(size: 13, weight: .bold, design: .rounded)).monospacedDigit()
                }
            }
            if !failed {
                Text(details(row)).font(.system(size: 10.5)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let note = row["self_reported"]["note"].string {
                    Text(note).font(.system(size: 10)).foregroundStyle(.tertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                HStack(spacing: 8) {
                    chip(ForecastCopy.confidence(row["self_reported"]["confidence"].string))
                    if let weight = row["weight"].double { chip("权重 \(String(format: "%.2f", weight))") }
                    if let updated = row["updated_at"].date { chip(Fmt.ago(updated, now: now) + "更新") }
                    if let url = row["provenance"].string {
                        Button { NSWorkspace.shared.open(URL(string: url)!) } label: { Text("原文").font(.system(size: 10)).foregroundStyle(.link) }
                            .buttonStyle(.plain)
                    }
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func details(_ row: JSON) -> String {
        var parts: [String] = []
        let raw24 = row["raw_24h"].double, head24 = row["headline_24h"].double
        if let raw24, let head24, abs(raw24 - head24) > 0.01 {
            parts.append("站内模型 \(Fmt.trim(raw24))%")
        }
        let band = row["band_24h"].array.compactMap { $0.double }
        if band.count == 2 {
            var text = "自评区间 \(Fmt.trim(band[0]))–\(Fmt.trim(band[1]))%"
            if let head = row["headline_24h"].double, head < band[0] || head > band[1] {
                text += "（与公布值不符）"
            }
            parts.append(text)
        }
        let reported = row["self_reported"]
        let cal = reported["calibration"]["24h"]
        let back = reported["backtest"]["24h"]
        if let score = cal["brier"].double ?? back["brier"].double {
            let sample = Int(cal["sample"].double ?? back["sample"].double ?? 0)
            let state = ForecastCopy.calibration(cal["state"].string ?? back["state"].string)
            let label = cal["brier"].double == nil ? "回测" : "校准"
            parts.append("Brier \(String(format: "%.3f", score))（\(label) \(sample) 样本 · \(state)）")
        }
        let cadence = row["cadence"]
        if let median = cadence["median_gap_days"].double { parts.append("间隔中位 \(Fmt.trim(median)) 天") }
        if let longest = cadence["longest_gap_days"].double { parts.append("最长 \(Fmt.trim(longest)) 天") }
        if let hint = row["latest_hint"]["quote"].string { parts.append("最近线索：\(hint)") }
        if let model = row["model_version"].string { parts.append("模型 \(model)") }
        return parts.joined(separator: " · ")
    }

    private func chip(_ text: String) -> some View {
        Text(text).font(.system(size: 9.5)).monospacedDigit()
            .padding(.horizontal, 5).padding(.vertical, 2)
            .background(Capsule().fill(Color.secondary.opacity(0.12)))
            .foregroundStyle(.secondary)
    }
}

// MARK: - Verified reset history

private struct HistoryCard: View {
    let events: [JSON]
    let now: Date

    var body: some View {
        Card {
            SectionTitle(text: "已验证重置记录", trailing: events.isEmpty ? nil : "近 \(min(events.count, 12)) 条")
            if events.isEmpty {
                Text("各站时间线都没抓到。").font(.system(size: 11)).foregroundStyle(.secondary)
            }
            ForEach(Array(events.prefix(12).enumerated()), id: \.offset) { _, event in
                HistoryRow(event: event, now: now)
            }
        }
    }
}

private struct HistoryRow: View {
    let event: JSON
    let now: Date

    var body: some View {
        let at = event["announced_at"].date
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(at.map { Fmt.day($0, now: now) + " " + Fmt.time($0) } ?? "—")
                .font(.system(size: 10.5, design: .rounded)).monospacedDigit().foregroundStyle(.secondary)
                .frame(width: 76, alignment: .leading)
            VStack(alignment: .leading, spacing: 1) {
                Text(event["summary"].string ?? event["kind"].string ?? "")
                    .font(.system(size: 11)).lineLimit(2)
                HStack(spacing: 6) {
                    Text(ForecastCopy.kind(event["kind"].string)).font(.system(size: 9.5, weight: .semibold))
                        .foregroundStyle(kindTint(event["kind"].string))
                    if event["scope"].string == "global" { Text("全员").font(.system(size: 9.5)).foregroundStyle(.secondary) }
                    let sources = event["sources"].array.count
                    if sources > 1 { Text("\(sources) 家印证").font(.system(size: 9.5)).foregroundStyle(.green.opacity(0.85)) }
                }
            }
            Spacer(minLength: 0)
            if let url = event["url"].string {
                Button { NSWorkspace.shared.open(URL(string: url)!) } label: {
                    Image(systemName: "arrow.up.right.square").font(.system(size: 10))
                }
                .buttonStyle(.plain).foregroundStyle(.link)
            }
        }
        .padding(.vertical, 2)
    }


    private func kindTint(_ kind: String?) -> Color {
        switch kind {
        case "reset": return .green
        case "banked", "credits": return .purple
        case "limits": return .orange
        default: return .secondary
        }
    }
}

// MARK: - Unavailable

private struct UnavailableCard: View {
    let source: Source

    var body: some View {
        Card {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("全员重置预测").font(.system(size: 13, weight: .semibold))
                    Text(Catalog.reason(source.reason ?? source.lastError)).font(.system(size: 11)).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                StatusPill(status: source.status)
            }
        }
    }
}
