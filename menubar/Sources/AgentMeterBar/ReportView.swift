import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// 用量报告窗口：左侧分享卡实时预览，右侧明细，底部复制 / 保存 PNG。
struct ReportView: View {
    @Environment(UsageStore.self) private var store
    /// 窗口皮肤跟随面板主题；这里直接读 store，避免环境值在自身 modifier 之外解析不到。
    private var theme: PanelTheme { store.theme }
    /// 与「本机消耗」页共用同一个时间段筛选。
    @AppStorage("usagePeriod") private var periodRaw = Period.today.rawValue

    @State private var style: PanelTheme = .aurora
    @State private var toast: String?
    /// 分享卡自然高度（未缩放），由预览自身量出；不建宿主视图，避免布局期重入。
    @State private var cardHeight: CGFloat = 0

    private var period: Period { Period(rawValue: periodRaw) ?? .today }

    private var data: ReportData? {
        guard let snapshot = store.snapshot else { return nil }
        return ReportData.build(snapshot: snapshot, period: period, now: store.now)
    }

    private static let fileDay: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "zh_CN")
        f.timeZone = Fmt.zone
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    var body: some View {
        // 一次 body 只聚合一次：明细与预览共用同一份 ReportData。
        let report = data
        VStack(spacing: 12) {
            header
            if store.snapshot == nil {
                VStack(spacing: 10) {
                    ProgressView()
                    Text(store.phase == .starting ? "正在启动本机后端…" : "正在读取用量…")
                        .font(.system(size: 11.5)).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                HStack(alignment: .top, spacing: 16) {
                    previewPane(report)
                    detailPane(report)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                actionBar(report)
            }
        }
        .padding(16)
        .frame(minWidth: 820, minHeight: 640)
        .themedRoot(store.theme)
    }

    // MARK: 顶部控制

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text("用量报告与分享").font(.system(size: 16, weight: .semibold))
                Text("在本机账本上聚合，只导出 PNG")
                    .font(.system(size: 10.5)).foregroundStyle(.tertiary)
                Spacer()
                PillTabs(items: Period.allCases, title: { $0.label },
                         selection: Binding(get: { period }, set: { periodRaw = $0.rawValue }), small: true)
                    .frame(width: 260)
            }
            HStack(alignment: .bottom, spacing: 14) {
                control("分享卡风格") {
                    Picker("分享卡风格", selection: $style) {
                        ForEach(PanelTheme.allCases) { Text($0.label).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .frame(width: 300)
                }
                Spacer()
                Text("竖版 · PNG 2× 输出")
                    .font(.system(size: 10)).foregroundStyle(.tertiary)
            }
        }
    }

    private func control<C: View>(_ title: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.system(size: 9.5)).foregroundStyle(.tertiary)
            content()
        }
    }

    // MARK: 预览

    private func previewPane(_ data: ReportData?) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("分享卡预览").font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                Spacer()
                if data != nil {
                    Text(cardHeight > 0 ? "竖版 · \(Int(ShareCard.width * 2))×\(Int(cardHeight * 2))"
                                        : "竖版 · PNG 2×")
                        .font(.system(size: 10, design: theme.numberDesign)).foregroundStyle(.tertiary)
                }
            }
            GeometryReader { geo in
                if let data {
                    let availableW = max(1, geo.size.width - 28)
                    let availableH = max(1, geo.size.height - 28)
                    let height = cardHeight > 0 ? cardHeight : ShareCard.width * 11 / 10
                    let scale = max(0.1, min(availableW / ShareCard.width, availableH / height))
                    ShareCard(data: data, theme: style)
                        .background(GeometryReader { inner in
                            Color.clear.preference(key: CardHeightKey.self, value: inner.size.height)
                        })
                        .scaleEffect(scale, anchor: .topLeading)
                        .frame(width: ShareCard.width * scale, height: height * scale, alignment: .topLeading)
                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .strokeBorder(Color.primary.opacity(0.15), lineWidth: 0.8))
                        .shadow(color: .black.opacity(0.22), radius: 14, y: 6)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    Card {
                        Text("当前时间段没有可分享的本机消耗记录。")
                            .font(.system(size: 12)).foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                }
            }
        }
        .onPreferenceChange(CardHeightKey.self) { height in
            if height > 0, abs(height - cardHeight) > 0.5 { cardHeight = height }
        }
    }

    // MARK: 明细

    private func detailPane(_ data: ReportData?) -> some View {
        ScrollView {
            VStack(spacing: 10) {
                if let data {
                    overviewCard(data)
                    costCard(data)
                    appsCard(data)
                    modelsCard(data)
                    sourceCard(data)
                } else {
                    Card {
                        Text("暂无可统计的数据。").font(.system(size: 12)).foregroundStyle(.secondary)
                    }
                }
            }
            .padding(.bottom, 4)
        }
        .scrollIndicators(.never)
        .frame(width: 348)
    }

    private func overviewCard(_ data: ReportData) -> some View {
        Card(tint: Color(red: 0.36, green: 0.52, blue: 1)) {
            Text("总览").font(.system(size: 12, weight: .semibold))
            InfoRow(symbol: "calendar", title: "时间范围", value: data.period.label,
                    detail: Fmt.moment(data.generatedAt, now: data.generatedAt) + " 生成")
            InfoRow(symbol: "number", title: "Token 总量", value: Fmt.tokens(data.totalTokens),
                    detail: data.totalIsLowerBound ? "部分日期为日汇总，总量为下界" : nil)
            InfoRow(symbol: "bolt.horizontal", title: "请求数", value: Fmt.grouped(data.requests))
            InfoRow(symbol: "arrow.down.left", title: "新输入", value: Fmt.tokens(data.freshInput))
            InfoRow(symbol: "arrow.up.right", title: "输出", value: Fmt.tokens(data.output))
            InfoRow(symbol: "arrow.triangle.2.circlepath", title: "缓存读 / 写",
                    value: "\(Fmt.tokens(data.cacheRead)) / \(Fmt.tokens(data.cacheWrite))")
            InfoRow(symbol: "target", title: "缓存命中率", value: data.cacheHitText,
                    detail: "命中 / (新输入 + 缓存读 + 缓存写)")
            InfoRow(symbol: "square.grid.2x2", title: "活跃应用", value: "\(data.appCount) 个")
        }
    }

    private func costCard(_ data: ReportData) -> some View {
        Card(tint: Color(red: 0.15, green: 0.82, blue: 0.62)) {
            Text("费用构成").font(.system(size: 12, weight: .semibold))
            InfoRow(symbol: "creditcard", title: "估算费用", value: data.costText,
                    detail: "API 等价估算，不是订阅账单")
            ForEach(data.costParts) { part in
                InfoRow(symbol: "chart.bar", title: part.label, value: part.text, valueTint: .secondary, nested: true)
            }
            if data.costParts.isEmpty {
                Text("没有可用的价格条目，费用显示为 —。")
                    .font(.system(size: 10.5)).foregroundStyle(.tertiary)
            }
            if !data.unpricedModels.isEmpty {
                Text("未计价模型：" + data.unpricedModels.joined(separator: "、"))
                    .font(.system(size: 10.5)).foregroundStyle(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func appsCard(_ data: ReportData) -> some View {
        Card {
            Text("Top 应用").font(.system(size: 12, weight: .semibold))
            ForEach(data.apps) { app in
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        Circle().fill(theme.tint(app.tint)).frame(width: 6, height: 6)
                            .themeGlow(app.tint, radius: 3, theme: theme)
                        Text(app.name).font(.system(size: 12, weight: .medium))
                        Spacer()
                        Text(Fmt.tokens(app.tokens))
                            .font(.system(size: 12, weight: .semibold)).monospacedDigit()
                        Text(app.cost).font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
                            .frame(minWidth: 54, alignment: .trailing)
                    }
                    Meter(fraction: app.fraction, tint: theme.tint(app.tint), height: 4)
                }
            }
            if data.apps.isEmpty {
                Text("当前时间段没有应用记录。").font(.system(size: 11)).foregroundStyle(.secondary)
            }
        }
    }

    private func modelsCard(_ data: ReportData) -> some View {
        Card {
            Text("Top 模型").font(.system(size: 12, weight: .semibold))
            ForEach(data.models) { model in
                HStack(spacing: 8) {
                    Text(model.name).font(.system(size: 11.5)).lineLimit(1).truncationMode(.middle)
                    Text(model.appLabel)
                        .font(.system(size: 9.5, weight: .medium))
                        .padding(.horizontal, 5).padding(.vertical, 1)
                        .foregroundStyle(theme.tint(model.tint))
                        .background(Capsule().fill(theme.tint(model.tint).opacity(theme == .minimal ? 0.06 : 0.13)))
                    Spacer()
                    if model.cost != "—" {
                        Text(model.cost).font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
                    }
                    Text(Fmt.tokens(model.tokens))
                        .font(.system(size: 11.5, weight: .medium)).monospacedDigit()
                }
            }
            if data.models.isEmpty {
                Text("当前时间段没有模型记录。").font(.system(size: 11)).foregroundStyle(.secondary)
            }
        }
    }

    private func sourceCard(_ data: ReportData) -> some View {
        Card {
            Text("数据来源").font(.system(size: 12, weight: .semibold))
            Text(data.sourceNote).font(.system(size: 10.5)).foregroundStyle(.secondary)
            Text("只读聚合本机账本，不读取对话内容；费用为 API 等价估算。")
                .font(.system(size: 10.5)).foregroundStyle(.tertiary)
            if data.periodStatus == "partial" {
                Text("部分日期仅有日汇总，总量与费用可能偏小。")
                    .font(.system(size: 10.5)).foregroundStyle(.orange)
            }
        }
    }

    // MARK: 底部操作

    private func actionBar(_ data: ReportData?) -> some View {
        HStack(spacing: 10) {
            if let toast {
                Label(toast, systemImage: "checkmark.circle.fill")
                    .font(.system(size: 11)).foregroundStyle(.green)
            } else if let data {
                Text(data.sourceNote).font(.system(size: 10)).foregroundStyle(.tertiary).lineLimit(1)
            }
            Spacer()
            Button("保存 PNG…") { save() }
            Button("复制图片") { copy() }
                .buttonStyle(.borderedProminent)
        }
        .disabled(data == nil)
    }

    private func copy() {
        guard let data else { return }
        guard let rendered = ShareCardRenderer.render(data: data, theme: style, scale: 2) else {
            show("生成图片失败")
            return
        }
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setData(rendered.png, forType: .png)
        show("已复制 \(Int(rendered.pixels.width))×\(Int(rendered.pixels.height)) PNG")
    }

    private func save() {
        guard let data else { return }
        guard let rendered = ShareCardRenderer.render(data: data, theme: style, scale: 2) else {
            show("生成图片失败")
            return
        }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.png]
        panel.canCreateDirectories = true
        panel.title = "保存用量报告 PNG"
        panel.nameFieldStringValue = "AgentMeter-用量报告-\(data.period.label)-\(Self.fileDay.string(from: data.generatedAt)).png"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try rendered.png.write(to: url)
            show("已保存 \(url.lastPathComponent)")
        } catch {
            show("保存失败：\(error.localizedDescription)")
        }
    }

    private func show(_ message: String) {
        toast = message
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(3))
            if toast == message { toast = nil }
        }
    }
}

/// 分享卡未缩放高度：预览按它算缩放比，避免在 body 里量宿主视图。
private struct CardHeightKey: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = max(value, nextValue())
    }
}
