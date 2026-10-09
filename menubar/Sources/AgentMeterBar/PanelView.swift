import SwiftUI

enum Tab: String, CaseIterable, Identifiable {
    case accounts, usage, apps
    var id: String { rawValue }
    var label: String {
        switch self {
        case .accounts: return "账户额度"
        case .usage: return "本机消耗"
        case .apps: return "应用覆盖"
        }
    }
}

struct PanelView: View {
    @Environment(UsageStore.self) private var store
    @AppStorage("panelTab") private var tabRaw = Tab.accounts.rawValue

    var body: some View {
        VStack(spacing: 0) {
            header
            if let snapshot = store.snapshot { CockpitStrip(snapshot: snapshot, now: store.now) }
            PillTabs(items: Tab.allCases, title: { $0.label },
                     selection: Binding(get: { Tab(rawValue: tabRaw) ?? .accounts }, set: { tabRaw = $0.rawValue }))
                .padding(.horizontal, 14)
                .padding(.bottom, 10)

            ThemeDivider()
            content
            ThemeDivider()
            footer
        }
        .frame(width: 420)
        .themedRoot(store.theme)
        .onAppear { store.panelOpened() }
    }

    // MARK: Header

    private var header: some View {
        HStack(spacing: 10) {
            HeaderLogo()
            VStack(alignment: .leading, spacing: 1) {
                HeaderTitle()
                Text(statusLine).font(.system(size: 10.5, design: store.theme == .neon ? .monospaced : .default))
                    .foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            themeMenu
            IconButton(symbol: "arrow.clockwise", help: "强制刷新（重新读取所有来源）", spinning: store.isBusy) {
                store.refresh()
            }
            .disabled(store.isBusy)
            settingsMenu
        }
        .padding(.horizontal, 14)
        .padding(.top, 12)
        .padding(.bottom, 10)
    }

    private var statusLine: String {
        switch store.phase {
        case .starting: return "正在启动本机后端…"
        case .loading: return "正在读取各来源…"
        case .refreshing: return "正在刷新…"
        case .idle: break
        }
        guard let s = store.snapshot, let t = s.collectedAt else { return "北京时间" }
        return "采集于 \(Fmt.timeSeconds(t)) · \(Fmt.ago(t, now: store.now))" + (s.servedFromCache ? " · 缓存" : "")
    }

    /// Quick switcher between the four styles, plainest first.
    private var themeMenu: some View {
        Menu {
            Picker("界面风格", selection: Binding(get: { store.theme }, set: { t in withAnimation(.easeInOut(duration: 0.25)) { store.theme = t } })) {
                ForEach(PanelTheme.allCases) { t in
                    Label("\(t.label) · \(t.blurb)", systemImage: t.symbol).tag(t)
                }
            }
            .pickerStyle(.inline)
        } label: {
            Image(systemName: "paintpalette")
                .font(.system(size: 12, weight: .semibold))
                .frame(width: 26, height: 26)
                .foregroundStyle(store.theme == .neon ? AnyShapeStyle(Neon.magenta) : AnyShapeStyle(.secondary))
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .help("切换界面风格：极简 · 原生 · 极光 · 霓虹")
    }

    private var settingsMenu: some View {
        Menu {
            Picker("界面风格", selection: Binding(get: { store.theme }, set: { store.theme = $0 })) {
                ForEach(PanelTheme.allCases) { Text($0.label).tag($0) }
            }
            Picker("菜单栏显示", selection: Binding(get: { store.menuBarMode }, set: { store.menuBarMode = $0 })) {
                ForEach(MenuBarMode.allCases) { Text($0.label).tag($0) }
            }
            Picker("滚动宽度", selection: Binding(get: { store.tickerWidth }, set: { store.tickerWidth = $0 })) {
                ForEach(TickerWidth.allCases) { Text($0.label).tag($0) }
            }
            Divider()
            Button("连接网页账户 / API 密钥…") { ConnectionManager.shared.showConnections() }
            Button("调整卡片顺序…") { SourceOrderWindow.show() }
            Toggle("读取 Claude 额度", isOn: Binding(get: { store.claudeEnabled }, set: { store.claudeEnabled = $0 }))
            Divider()
            Toggle("额度与到期提醒", isOn: Binding(get: { store.notificationsEnabled }, set: { store.notificationsEnabled = $0 }))
            Picker("额度不足阈值", selection: Binding(get: { store.lowQuotaThreshold }, set: { store.lowQuotaThreshold = $0 })) {
                ForEach([10.0, 20.0, 30.0], id: \.self) { Text("剩余 ≤ \(Int($0))%").tag($0) }
            }
            .disabled(!store.notificationsEnabled)
            Button("发送测试通知") { Notifier.shared.sendTest() }
            Divider()
            Toggle("开机启动", isOn: Binding(get: { store.launchAtLogin }, set: { store.setLaunchAtLogin($0) }))
            Divider()
            if let dir = store.projectDirectory {
                Button("打开后端目录") { NSWorkspace.shared.open(dir) }
                Button("查看后端日志") {
                    NSWorkspace.shared.open(dir.appendingPathComponent(".runtime/menubar-backend.log"))
                }
            }
            Divider()
            Button("退出 Agent 用量") { NSApp.terminate(nil) }
        } label: {
            Image(systemName: "ellipsis")
                .font(.system(size: 12, weight: .semibold))
                .frame(width: 26, height: 26)
                .background(Circle().fill(Color.primary.opacity(0.05)))
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
    }

    // MARK: Content

    static var expandForPreview = false

    @ViewBuilder private func tabContent(_ snapshot: Snapshot) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            if let error = store.errorMessage { ErrorBanner(message: error) }
            switch Tab(rawValue: tabRaw) ?? .accounts {
            case .accounts: AccountsView(snapshot: snapshot, now: store.now)
            case .usage: UsageView(snapshot: snapshot, now: store.now)
            case .apps: AppsView(snapshot: snapshot)
            }
        }
        .padding(14)
    }

    @ViewBuilder private var content: some View {
        if let snapshot = store.snapshot {
            if Self.expandForPreview {
                tabContent(snapshot)
            } else {
                ScrollView { tabContent(snapshot) }.scrollIndicators(.never).frame(height: 480)
            }
        } else if let error = store.errorMessage {
            VStack(spacing: 12) {
                Image(systemName: "bolt.horizontal.circle").font(.system(size: 34)).foregroundStyle(.orange)
                Text("无法读取用量").font(.system(size: 14, weight: .semibold))
                Text(error).font(.system(size: 11.5)).foregroundStyle(.secondary).multilineTextAlignment(.center)
                Button("重试") { store.refresh() }.controlSize(.regular)
            }
            .padding(28)
            .frame(maxWidth: .infinity)
            .frame(height: 300)
        } else {
            VStack(spacing: 12) {
                ProgressView().controlSize(.regular)
                Text(store.phase == .starting ? "正在启动本机后端…" : "正在读取账户额度与本机记录…")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
                Text("首次采集通常需要几秒").font(.system(size: 10.5)).foregroundStyle(.tertiary)
            }
            .frame(maxWidth: .infinity)
            .frame(height: 300)
        }
    }

    // MARK: Footer

    private var footer: some View {
        HStack(spacing: 6) {
            if let s = store.snapshot {
                let summary = s.summary
                Image(systemName: "square.stack.3d.up").font(.system(size: 10))
                Text("\(Int(summary["applications"].double ?? 0)) 个应用 · \(Int(summary["available_fields"].double ?? 0)) 项已采集 · \(Int(summary["partial_fields"].double ?? 0)) 项部分")
            } else {
                Text("本机只读 · 127.0.0.1:8769")
            }
            Spacer()
            Text("北京时间")
        }
        .font(.system(size: 10.5))
        .foregroundStyle(.secondary)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }
}

/// App mark next to the title; grows louder with the theme.
private struct HeaderLogo: View {
    @Environment(\.panelTheme) private var theme

    var body: some View {
        let symbol = Image(systemName: "gauge.with.dots.needle.67percent")
        switch theme {
        case .minimal:
            EmptyView()
        case .native:
            symbol.font(.system(size: 13, weight: .semibold)).foregroundStyle(.white)
                .frame(width: 28, height: 28)
                .background(RoundedRectangle(cornerRadius: 7, style: .continuous).fill(Color.accentColor))
        case .aurora:
            ZStack {
                Circle().fill(LinearGradient(colors: [Color(red: 0.36, green: 0.52, blue: 1), Color(red: 0.78, green: 0.36, blue: 0.98)],
                                             startPoint: .topLeading, endPoint: .bottomTrailing))
                    .shadow(color: Color(red: 0.55, green: 0.4, blue: 1).opacity(0.8), radius: 8)
                symbol.font(.system(size: 14, weight: .bold)).foregroundStyle(.white)
            }
            .frame(width: 32, height: 32)
        case .neon:
            ZStack {
                Hexagon().fill(Color.black.opacity(0.6))
                Hexagon().stroke(Neon.rim, lineWidth: 1.5)
                symbol.font(.system(size: 14, weight: .bold)).foregroundStyle(Neon.cyan)
            }
            .frame(width: 32, height: 32)
            .shadow(color: Neon.magenta, radius: 4)
            .shadow(color: Neon.cyan.opacity(0.7), radius: 12)
        }
    }
}

private struct HeaderTitle: View {
    @Environment(\.panelTheme) private var theme

    var body: some View {
        switch theme {
        case .minimal:
            Text("Agent 用量").font(.system(size: 14, weight: .medium)).kerning(0.5)
        case .native:
            Text("Agent 用量").font(.system(size: 14, weight: .semibold))
        case .aurora:
            Text("Agent 用量").font(.system(size: 15, weight: .heavy, design: .rounded))
                .foregroundStyle(LinearGradient(colors: [.primary, Color(red: 0.6, green: 0.5, blue: 1)], startPoint: .leading, endPoint: .trailing))
        case .neon:
            // Chromatic aberration: magenta and cyan ghosts behind the white title.
            let title = Text("AGENT//用量").font(.system(size: 15, weight: .heavy, design: .monospaced)).kerning(1)
            ZStack {
                title.foregroundStyle(Neon.magenta).offset(x: -1.2, y: 0.4).opacity(0.9)
                title.foregroundStyle(Neon.cyan).offset(x: 1.2, y: -0.4).opacity(0.9)
                title.foregroundStyle(.white)
            }
            .shadow(color: Neon.magenta.opacity(0.8), radius: 6)
        }
    }
}

private struct Hexagon: Shape {
    func path(in r: CGRect) -> Path {
        var p = Path()
        for i in 0..<6 {
            let a = Double(i) * .pi / 3 - .pi / 2
            let pt = CGPoint(x: r.midX + r.width / 2 * cos(a), y: r.midY + r.height / 2 * sin(a))
            if i == 0 { p.move(to: pt) } else { p.addLine(to: pt) }
        }
        p.closeSubpath()
        return p
    }
}

struct ErrorBanner: View {
    let message: String
    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
            Text("刷新失败，显示上次数据。\(message)").font(.system(size: 11)).foregroundStyle(.secondary)
            Spacer(minLength: 0)
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Color.orange.opacity(0.1)))
    }
}

struct AppsView: View {
    let snapshot: Snapshot

    var body: some View {
        let rows = snapshot.coverage.sorted { ($0.collected, $0.installed ? 1 : 0) > ($1.collected, $1.installed ? 1 : 0) }
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                legend("available", "已采集")
                legend("partial", "部分")
                legend("stale", "过期")
                legend("error", "失败")
                legend("not_connected", "未连接")
                legend("not_supported", "未接入")
            }
            .padding(.horizontal, 2)
            Card {
                ForEach(Array(rows.enumerated()), id: \.element.id) { i, row in
                    if i > 0 { Divider().opacity(0.4) }
                    HStack(spacing: 8) {
                        VStack(alignment: .leading, spacing: 1) {
                            Text(row.name).font(.system(size: 12, weight: row.collected > 0 ? .medium : .regular))
                                .foregroundStyle(row.collected > 0 ? .primary : .secondary)
                                .lineLimit(1)
                            Text(row.installed ? (row.version.map { "v" + $0 } ?? "已安装") : "仅有历史记录")
                                .font(.system(size: 9.5)).foregroundStyle(.tertiary)
                        }
                        Spacer(minLength: 6)
                        HStack(spacing: 3) {
                            ForEach(row.fields, id: \.name) { f in
                                RoundedRectangle(cornerRadius: 2)
                                    .fill(Catalog.statusColor(f.status).opacity(f.status == "not_supported" || f.status == "not_provided" ? 0.35 : 0.9))
                                    .frame(width: 7, height: 12)
                                    .help("\(f.name)：\(Catalog.statusLabel(f.status))")
                            }
                        }
                        if row.installed, let path = row.path, path.hasSuffix(".app") {
                            Button { AppLauncher.open(.init(id: path, name: row.name, path: path, url: nil)) } label: {
                                Image(nsImage: AppLauncher.icon(atPath: path)).resizable().frame(width: 18, height: 18)
                            }
                            .buttonStyle(.plain)
                            .help("打开 " + row.name)
                        }
                        Text("\(row.collected)/\(row.fields.count)")
                            .font(.system(size: 10.5, weight: .medium)).monospacedDigit()
                            .foregroundStyle(row.collected > 0 ? .primary : .tertiary)
                            .frame(width: 34, alignment: .trailing)
                    }
                }
            }
            Text("每格对应一类指标：额度、重置、重置卡、积分、Token、费用、续费、续费倒计时、续费金额、积分更新、积分更新倒计时。")
                .font(.system(size: 10)).foregroundStyle(.tertiary)
                .padding(.horizontal, 2)
        }
    }

    private func legend(_ status: String, _ text: String) -> some View {
        HStack(spacing: 4) {
            RoundedRectangle(cornerRadius: 2).fill(Catalog.statusColor(status).opacity(status == "not_supported" ? 0.35 : 0.9))
                .frame(width: 7, height: 10)
            Text(text).font(.system(size: 10)).foregroundStyle(.secondary)
        }
    }
}


/// Cockpit row: one gauge per account, its quota windows as concentric rings
/// (5 小时 outside, 7 天 inside); click opens the app.
struct CockpitStrip: View {
    let snapshot: Snapshot
    let now: Date
    @Environment(\.panelTheme) private var theme

    private struct Window {
        let label: String
        let remaining: Double
        let reset: Date?
    }

    private struct Gauge: Identifiable {
        let id: String
        let source: String
        let name: String
        let windows: [Window]
    }

    private var gauges: [Gauge] {
        snapshot.accountSources.compactMap { s in
            // Time windows only: call counts like ZCode's monthly MCP bucket stay on the card.
            let rows = Catalog.sortedQuotas((s.metric("quota")?.value.rows ?? [])
                .filter { $0["remaining_percent"].double != nil && $0["bucket"].string != "mcp" })
            guard !rows.isEmpty else { return nil }
            return Gauge(id: s.id, source: s.baseID, name: s.shortName,
                         windows: rows.map { Window(label: Self.shortWindow($0), remaining: $0["remaining_percent"].double ?? 0,
                                                    reset: $0["resets_at"].date) })
        }
    }

    /// "5h" / "7d" / "月" — just enough to tell the rings apart.
    private static func shortWindow(_ q: JSON) -> String {
        switch Catalog.windowMinutes(q) {
        case 300: return "5h"
        case 1440: return "1d"
        case 10080: return "7d"
        case 43200: return "月"
        default: return Catalog.bucketLabel(q).replacingOccurrences(of: " ", with: "")
        }
    }

    var body: some View {
        let list = gauges
        if !list.isEmpty {
            ScrollView(.horizontal) {
                HStack(spacing: 14) {
                    ForEach(list) { g in
                        Button {
                            if let t = AppLauncher.targets(for: g.source, in: snapshot).first { AppLauncher.open(t) }
                        } label: { gaugeView(g) }
                        .buttonStyle(.plain)
                        .help(g.windows.map { "\($0.label) 剩余 \(Fmt.percent($0.remaining.rounded()))" }.joined(separator: "，")
                              + " · 打开 " + Catalog.brand(g.source).name)
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 4)
            }
            .scrollIndicators(.never)
            .padding(.bottom, 8)
        }
    }

    private func gaugeView(_ g: Gauge) -> some View {
        VStack(spacing: 3) {
            ZStack(alignment: .bottomTrailing) {
                if g.windows.count == 1 {
                    Ring(remaining: g.windows[0].remaining, size: 46, lineWidth: 4.5, caption: nil)
                } else {
                    StackedRing(remaining: g.windows.map(\.remaining), size: g.windows.count > 2 ? 56 : 50,
                                lineWidth: g.windows.count > 2 ? 3.5 : 4)
                }
                if let icon = AppLauncher.icon(for: g.source, in: snapshot) {
                    Image(nsImage: icon).resizable().frame(width: 15, height: 15).offset(x: 3, y: 3)
                }
            }
            Text(g.name).font(.system(size: 9.5, weight: .semibold, design: theme == .neon ? .monospaced : .default)).lineLimit(1)
            if g.windows.count > 1 {
                // Each ring's value, outer first, in its own health colour.
                HStack(spacing: 4) {
                    ForEach(g.windows.indices, id: \.self) { i in
                        let w = g.windows[i]
                        (Text(w.label).foregroundStyle(.secondary)
                         + Text(" \(Int(w.remaining.rounded()))").foregroundStyle(theme.health(w.remaining)))
                    }
                }
                .font(.system(size: 8.5, weight: .medium, design: theme.numberDesign))
                .monospacedDigit()
                .lineLimit(1)
                .fixedSize()
            }
            Text(g.windows.first?.reset.map { Fmt.shortCountdown(to: $0, now: now, past: "待刷新") } ?? "—")
                .font(.system(size: 9)).foregroundStyle(.secondary).monospacedDigit()
        }
        .frame(minWidth: 52)
    }
}
