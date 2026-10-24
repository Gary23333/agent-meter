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
                TiboHeroCard(source: source, forecast: forecast.value,
                             targets: source.metric("known_reset_countdown")?.value["targets"].array ?? [], now: now)
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
                    QSectionTitle(symbol: "clock.arrow.2.circlepath", text: "重置预测")
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

/// Semantic colours for this page, resolved per theme so minimal stays
/// monochrome and neon stays on its own palette.
struct ForecastTone {
    let theme: PanelTheme

    var good: Color { theme.health(100) }
    var warn: Color { theme.health(30) }
    var bad: Color { theme.health(5) }
    var special: Color {
        switch theme {
        case .minimal: return .primary
        case .native: return Color(nsColor: .systemPurple)
        case .porcelain, .aurora, .titanium: return Color(red: 0.70, green: 0.36, blue: 0.98)
        case .neon, .prism: return Neon.violet
        }
    }
    var link: Color {
        switch theme {
        case .minimal: return .primary
        case .native: return Color(nsColor: .linkColor)
        case .porcelain, .aurora, .titanium: return Color(red: 0.40, green: 0.45, blue: 1.0)
        case .neon, .prism: return Neon.cyan
        }
    }
    /// Published values get the accent; model-only values stay muted.
    var dot: Color {
        switch theme {
        case .minimal: return .primary
        case .native: return .accentColor
        case .porcelain, .aurora, .titanium: return Color(red: 0.40, green: 0.45, blue: 1.0)
        case .neon, .prism: return Neon.cyan
        }
    }
    var band: AnyShapeStyle {
        switch theme {
        case .minimal: return AnyShapeStyle(Color.primary.opacity(0.45))
        case .native: return AnyShapeStyle(Color.accentColor.opacity(0.55))
        default: return AnyShapeStyle(theme.figure(theme.accent).opacity(0.75))
        }
    }
    var chip: Color { theme.isLuminous ? theme.accent[0].opacity(0.14) : Color.secondary.opacity(0.12) }
}

extension ForecastCopy {
    /// Countdown wording shared by the list rows and the resetter's ticket.
    static func countdown(_ target: JSON, now: Date) -> String {
        switch target["state"].string ?? "no_clock" {
        case "no_clock": return "未给时间"
        case "label_only": return target["kind"].string == "typical_window" ? "仅文字描述" : "未给时间"
        case "inside_window": return "窗口进行中"
        case "elapsed_awaiting_landing": return "已过 · 等待落地"
        default: return target["close_at"].date.map { Fmt.countdown(to: $0, now: now) } ?? "—"
        }
    }

    /// One line for the ticket strip: the first target with a clock.
    static func ticket(_ targets: [JSON], now: Date) -> String {
        guard let target = targets.first(where: { $0["close_at"].date != nil }) else {
            return targets.isEmpty ? "暂无可倒计时的时段" : "时段只有文字描述"
        }
        let promised = target["kind"].string == "promised_reset"
        let name = promised ? "已公告时段" : "常见公告时段"
        switch target["state"].string {
        case "inside_window": return name + " · 进行中"
        case "elapsed_awaiting_landing": return name + " · 已过，等待落地"
        default:
            if let open = target["open_at"].date, open > now {
                return name + " · " + Fmt.countdown(to: open, now: now)
            }
            return name + " · " + countdown(target, now: now)
        }
    }
}

// MARK: - Hero: Tibo and the resetter

private struct TiboHeroCard: View {
    let source: Source
    let forecast: JSON
    let targets: [JSON]
    let now: Date
    @Environment(\.panelTheme) private var theme
    @Environment(UsageStore.self) private var store
    @AppStorage("forecastHorizon") private var horizon = "48h"

    var body: some View {
        let mood = TiboMood.from(forecast: forecast, targets: targets, now: now)
        let horizons = forecast["ensemble"]["horizons"].object
        let median48 = horizons["48h"]?["weighted_median"].double
        let median24 = horizons["24h"]?["weighted_median"].double
        let selected = horizon == "24h" ? median24 : median48
        let line = speech(mood, median48: median48, horizons: horizons)
        Card(tint: theme.accent[0]) {
            HStack(alignment: .center, spacing: 8) {
                QSticker(symbol: "arrow.counterclockwise")
                VStack(alignment: .leading, spacing: 1) {
                    Text("Tibo 重置器")
                        .font(.system(size: 13.5, weight: .heavy, design: theme.isLuminous ? .monospaced : .rounded))
                        .foregroundStyle(theme.figure(theme.accent))
                    Text("ChatGPT / Codex 全员重置 · 第三方预测")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                StatusPill(status: forecast["cache_state"].string == "stale" ? "stale" : source.status)
            }
            SpeechBubble(title: line.0, detail: line.1)
            HStack(alignment: .bottom, spacing: 6) {
                TiboChibi(mood: mood).frame(width: 96, height: 120)
                ResetterMachine(percent: selected, horizon: horizon,
                                secondary: (horizon == "24h" ? median48 : median24).map { (horizon == "24h" ? "48h " : "24h ") + Fmt.trim($0) + "%" },
                                ticket: ForecastCopy.ticket(targets, now: now),
                                pressed: mood.pressing)
            }
            .padding(.top, -4)
            HStack(spacing: 8) {
                Picker("观察窗", selection: $horizon) {
                    Text("24h").tag("24h"); Text("48h").tag("48h")
                }
                .pickerStyle(.segmented).frame(width: 108).controlSize(.small)
                Label("\(Int(forecast["ensemble"]["n_sources"].double ?? 0)) 家可用",
                      systemImage: "antenna.radiowaves.left.and.right")
                if let at = source.observedAt { Text("抓取 " + Fmt.ago(at, now: now)) }
                Spacer(minLength: 0)
                IconButton(symbol: "arrow.clockwise", help: "立即刷新预测与全部用量", spinning: store.isBusy) { store.refresh() }
                    .disabled(store.isBusy)
            }
            .font(.system(size: 10.5)).foregroundStyle(.secondary)
            if let disclaimer = forecast["disclaimer"].string {
                Text(disclaimer)
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    /// Bubble copy restates data already on the page; it never adds a claim.
    private func speech(_ mood: TiboMood, median48: Double?, horizons: [String: JSON]) -> (String, String) {
        let pct = median48.map { Fmt.trim($0) + "%" } ?? "—"
        switch mood {
        case .resetting:
            let target = targets.first { $0["kind"].string == "promised_reset" && $0["state"].string == "inside_window" }
            let close = target?["close_at"].date.map { Fmt.moment($0, now: now) } ?? "公告时段内"
            return ("按下去啦！公告时段进行中", "\(target?["label"].string ?? "已公告的重置")：\(close) 前落地，记得去 Codex 看额度。")
        case .celebrate:
            let latest = forecast["history_events"].array.first
            let at = latest?["announced_at"].date.map { Fmt.ago($0, now: now) } ?? "刚刚"
            let n = latest?["sources"].array.count ?? 0
            return ("叮～刚重置过啦！", "追踪站记录到 \(at)有一次全员重置" + (n > 1 ? "，\(n) 家印证。" : "，目前仅 1 家记录。"))
        case .excited:
            if !forecast["promises"].array.isEmpty {
                return ("站内挂着承诺，按钮已就位！", "已承诺还会再重置一次，但没给时间；48 小时中位 \(pct)。")
            }
            return ("各站都挺看好，手指已经放上去了", "48 小时内中位 \(pct)。")
        case .waiting:
            let close = horizons["48h"]?["agreement"].string == "close"
            return ("手放在按钮上……再等等", "48 小时内中位 \(pct)，各站" + (close ? "看法接近。" : "分歧较大。"))
        case .sleepy:
            return ("Zzz……最近没什么动静", "48 小时内中位只有 \(pct)。")
        case .offline:
            return ("追踪站还没回信", "暂时没有任何一家给出可用预测。")
        }
    }
}

// MARK: - Band and weighted median

private struct EnsembleCard: View {
    let ensemble: JSON

    var body: some View {
        let horizons = ensemble["horizons"].object
        Card {
            QSectionTitle(symbol: "chart.bar.fill", text: "下次全员重置概率", trailing: "各站自己公布的数值")
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
    @Environment(\.panelTheme) private var theme

    var body: some View {
        let values = band["values"].array
        let low = band["min"].double ?? 0
        let high = band["max"].double ?? 0
        let tone = ForecastTone(theme: theme)
        let close = band["agreement"].string == "close"
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(horizon == "24h" ? "24 小时内" : "48 小时内")
                    .font(.system(size: 11.5)).foregroundStyle(.secondary)
                Spacer()
                Text("\(Fmt.trim(low))–\(Fmt.trim(high))%")
                    .font(theme.number(13)).monospacedDigit()
                Text("中位 \(Fmt.trim(band["weighted_median"].double ?? 0))%")
                    .font(.system(size: 11.5, weight: .medium, design: .rounded))
                    .foregroundStyle(.secondary).monospacedDigit()
                Text(band["agreement"].string == "close" ? "接近" : "分歧")
                    .font(.system(size: 9.5, weight: .semibold))
                    .padding(.horizontal, 5).padding(.vertical, 2)
                    .background(Capsule().fill((close ? tone.good : tone.warn).opacity(0.15)))
                    .foregroundStyle(close ? tone.good : tone.warn)
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.secondary.opacity(0.16)).frame(height: 5)
                    Capsule()
                        .fill(tone.band)
                        .frame(width: max(3, geo.size.width * (high - low) / 100), height: 5)
                        .offset(x: geo.size.width * low / 100)
                    ForEach(Array(values.enumerated()), id: \.offset) { _, item in
                        let pct = item["percent"].double ?? 0
                        Circle().fill(dotTint(item["basis"].string)).frame(width: 7, height: 7)
                            .offset(x: geo.size.width * pct / 100 - 3.5, y: -1)
                            .themeGlow(dotTint(item["basis"].string), radius: 2, theme: theme)
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
        basis == "published_answer" ? ForecastTone(theme: theme).dot : Color.secondary.opacity(0.6)
    }

}

// MARK: - Active promise

/// A promise without a machine-readable clock is a banner, not a countdown.
private struct PromiseCard: View {
    let promises: [JSON]
    let now: Date
    @Environment(\.panelTheme) private var theme

    var body: some View {
        let tone = ForecastTone(theme: theme)
        if !promises.isEmpty {
            Card(tint: tone.warn) {
                QSectionTitle(symbol: "hand.raised.fill", text: "站内已挂承诺", trailing: "\(promises.count) 条 · 无兑现时间", tint: tone.warn)
                ForEach(Array(promises.enumerated()), id: \ .offset) { _, item in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(alignment: .center, spacing: 6) {
                            TiboFace(mood: .excited, size: 18)
                            Text(ForecastCopy.source(item["source"].string))
                                .font(.system(size: 11.5, weight: .medium))
                            if let floor = item["floor_percent"].double {
                                Text("该站据此给 \(Fmt.trim(floor))%")
                                    .font(.system(size: 10.5)).foregroundStyle(tone.warn)
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
                                Text("“\(quote)”").font(.system(size: 10.5)).foregroundStyle(tone.link)
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
            QSectionTitle(symbol: "alarm.fill", text: "已知重置倒计时", trailing: targets.isEmpty ? nil : "\(targets.count) 项")
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
    @Environment(\.panelTheme) private var theme

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
                    } label: { Text(quote).font(.system(size: 10)).foregroundStyle(ForecastTone(theme: theme).link) }
                        .buttonStyle(.plain)
                        .lineLimit(2)
                }
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 1) {
                Text(ForecastCopy.countdown(target, now: now))
                    .font(theme.number(12.5)).monospacedDigit()
                    .foregroundStyle(tint(state))
                Text(sourcesBadge(target["sources"].array)).font(.system(size: 9.5)).foregroundStyle(.tertiary)
            }
        }
        .padding(.vertical, 2)
    }

    private func tint(_ state: String) -> Color {
        switch state {
        case "inside_window": return ForecastTone(theme: theme).good
        case "elapsed_awaiting_landing": return ForecastTone(theme: theme).warn
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
    @State private var expanded = false

    var body: some View {
        Card {
            DisclosureGroup(isExpanded: $expanded) {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                        SourceRow(row: row, now: now)
                        if row != rows.last { Divider().opacity(0.4) }
                    }
                }
                .padding(.top, 8)
            } label: {
                QSectionTitle(symbol: "antenna.radiowaves.left.and.right", text: "各站口径",
                              trailing: expanded ? "收起" : "\(rows.count) 家 · 展开")
            }
            .tint(.secondary)
        }
    }
}

private struct SourceRow: View {
    let row: JSON
    let now: Date
    @Environment(\.panelTheme) private var theme

    var body: some View {
        let tone = ForecastTone(theme: theme)
        let failed = (row["status"].string ?? "") == "error"
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(row["name"].string ?? row["source"].string ?? "")
                    .font(.system(size: 12, weight: .medium))
                if failed {
                    Text(Catalog.reason(row["reason"].string)).font(.system(size: 10.5)).foregroundStyle(tone.bad).lineLimit(2)
                }
                Spacer(minLength: 6)
                if !failed {
                    Text("\(Fmt.trim(row["headline_24h"].double ?? row["raw_24h"].double ?? 0))% / \(Fmt.trim(row["headline_48h"].double ?? row["raw_48h"].double ?? 0))%")
                        .font(theme.number(13)).monospacedDigit()
                        .foregroundStyle(theme.figure(theme.accent))
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
                        Button { NSWorkspace.shared.open(URL(string: url)!) } label: { Text("原文").font(.system(size: 10)).foregroundStyle(tone.link) }
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
            .background(Capsule().fill(ForecastTone(theme: theme).chip))
            .foregroundStyle(.secondary)
    }
}

// MARK: - Verified reset history

private struct HistoryCard: View {
    let events: [JSON]
    let now: Date
    @State private var expanded = false

    var body: some View {
        Card {
            Button {
                withAnimation(.easeInOut(duration: 0.2)) { expanded.toggle() }
            } label: {
                HStack {
                    QSectionTitle(symbol: "checkmark.seal.fill", text: "已验证重置记录",
                                  trailing: events.isEmpty ? nil : (expanded ? "收起" : "\(events.count) 条 · 展开"))
                    Image(systemName: expanded ? "chevron.up" : "chevron.down")
                        .font(.system(size: 9, weight: .semibold)).foregroundStyle(.tertiary)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(events.count <= 3)
            if events.isEmpty {
                Text("各站时间线都没抓到。").font(.system(size: 11)).foregroundStyle(.secondary)
            }
            ForEach(Array(events.prefix(expanded ? 12 : 3).enumerated()), id: \.offset) { _, event in
                HistoryRow(event: event, now: now)
            }
        }
    }
}

private struct HistoryRow: View {
    let event: JSON
    let now: Date
    @Environment(\.panelTheme) private var theme

    var body: some View {
        let tone = ForecastTone(theme: theme)
        let at = event["announced_at"].date
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(at.map { Fmt.day($0, now: now) + " " + Fmt.time($0) } ?? "—")
                .font(.system(size: 10.5, design: .rounded)).monospacedDigit().foregroundStyle(.secondary)
                .frame(width: 76, alignment: .leading)
            VStack(alignment: .leading, spacing: 1) {
                Text(event["summary"].string ?? event["kind"].string ?? "")
                    .font(.system(size: 11)).lineLimit(2)
                HStack(spacing: 6) {
                    if event["kind"].string == "reset" { TiboFace(mood: .celebrate, size: 14) }
                    Text(ForecastCopy.kind(event["kind"].string)).font(.system(size: 9.5, weight: .semibold))
                        .foregroundStyle(kindTint(event["kind"].string))
                    if event["scope"].string == "global" { Text("全员").font(.system(size: 9.5)).foregroundStyle(.secondary) }
                    let sources = event["sources"].array.count
                    if sources > 1 { Text("\(sources) 家印证").font(.system(size: 9.5)).foregroundStyle(tone.good.opacity(0.85)) }
                }
            }
            Spacer(minLength: 0)
            if let url = event["url"].string {
                Button { NSWorkspace.shared.open(URL(string: url)!) } label: {
                    Image(systemName: "arrow.up.right.square").font(.system(size: 10))
                }
                .buttonStyle(.plain).foregroundStyle(tone.link)
            }
        }
        .padding(.vertical, 2)
    }


    private func kindTint(_ kind: String?) -> Color {
        switch kind {
        case "reset": return ForecastTone(theme: theme).good
        case "banked", "credits": return ForecastTone(theme: theme).special
        case "limits": return ForecastTone(theme: theme).warn
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
                TiboChibi(mood: .offline).frame(width: 44, height: 56)
                VStack(alignment: .leading, spacing: 3) {
                    Text("Tibo 重置器暂时休息").font(.system(size: 13, weight: .semibold))
                    Text(Catalog.reason(source.reason ?? source.lastError)).font(.system(size: 11)).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                StatusPill(status: source.status)
            }
        }
    }
}
