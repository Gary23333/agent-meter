import SwiftUI

enum Tab: String, CaseIterable, Identifiable {
    case accounts, apps, forecast, usage, pet, collection
    var id: String { rawValue }
    var label: String {
        switch self {
        case .accounts: return "账户额度"
        case .forecast: return "重置预测"
        case .usage:       return "本机消耗"
        case .apps:        return "应用"
        case .pet:         return "桌宠"
        case .collection:  return "收集"
        }
    }
}

struct PanelView: View {
    @Environment(UsageStore.self) private var store
    @AppStorage("panelTab") private var tabRaw = Tab.accounts.rawValue

    /// "activity"/"projects" are pre-merge tab ids that now live inside the apps tab.
    private var selectedTab: Tab {
        if tabRaw == "activity" || tabRaw == "projects" { return .apps }
        return Tab(rawValue: tabRaw) ?? .accounts
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            if let snapshot = store.snapshot { CockpitStrip(snapshot: snapshot, now: store.now) }
            PillTabs(items: Tab.allCases, title: { $0.label },
                     selection: Binding(get: { selectedTab }, set: { tabRaw = $0.rawValue }))
                .padding(.horizontal, 14)
                .padding(.bottom, 10)

            ThemeDivider()
            content
            ThemeDivider()
            footer
        }
        .frame(width: 420)
        .themedRoot(store.theme)
        .overlay { celebration }
        .animation(.easeInOut(duration: 0.3), value: store.pendingUnlocks.first)
        .animation(.easeInOut(duration: 0.25), value: store.detailTrophy)
        .onAppear { store.panelOpened() }
    }

    // MARK: Celebration

    @State private var shareToast: String?

    /// The unlock queue wins over a detail page the user opened.
    @ViewBuilder private var celebration: some View {
        if let data = store.snapshot?.collection {
            if let unlock = store.pendingUnlocks.first {
                stage(unlock, data, mode: .unlock(position: store.shownUnlocks + 1,
                                                  total: store.shownUnlocks + store.pendingUnlocks.count)) {
                    withAnimation(.spring(response: 0.4)) { store.dismissUnlock() }
                    if store.pendingUnlocks.isEmpty { tabRaw = Tab.collection.rawValue }
                }
            } else if let detail = store.detailTrophy {
                stage(detail, data, mode: .detail) {
                    withAnimation(.spring(response: 0.35)) { store.detailTrophy = nil }
                }
            }
        }
    }

    private func stage(_ unlock: Unlock, _ data: CollectionData, mode: TrophyStage.Mode,
                       dismiss: @escaping () -> Void) -> some View {
        TrophyStage(unlock: unlock, data: data, mode: mode,
                    onShare: { action in
                        let name = "AgentMeter-" + (data.medals.first { $0.id == unlock.id }?.name ?? data.def(unlock.id)?.name ?? "收藏")
                        let message = TrophyShare.perform(action, png: TrophyShare.png(TrophyShareCard(unlock: unlock, data: data)), name: name)
                        withAnimation(.spring(response: 0.3)) { shareToast = message }
                        Task { @MainActor in
                            try? await Task.sleep(for: .seconds(2.5))
                            withAnimation { if shareToast == message { shareToast = nil } }
                        }
                    },
                    onDismiss: dismiss)
            .overlay(alignment: .top) {
                if let shareToast {
                    Text(shareToast).font(.system(size: 11, weight: .semibold)).foregroundStyle(.white)
                        .padding(.horizontal, 12).padding(.vertical, 6)
                        .background(Capsule().fill(.black.opacity(0.6)))
                        .padding(.top, 12)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
            }
            .transition(.opacity.combined(with: .scale(scale: 1.04)))
    }

    // MARK: Header

    private var header: some View {
        HStack(spacing: 10) {
            HeaderLogo()
            VStack(alignment: .leading, spacing: 1) {
                HeaderTitle()
                Text(statusLine).font(.system(size: 10.5, design: store.theme == .neon ? .monospaced : .default))
                    .themeForeground(.secondary).lineLimit(1)
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

    /// Quick switcher between the seven styles, plainest first.
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
                .foregroundStyle(store.theme.isLuminous ? AnyShapeStyle(store.theme.accent[0]) : AnyShapeStyle(.secondary))
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .help("切换界面风格：极简 · 原生 · 瓷白 · 极光 · 钛影 · 霓虹 · 棱镜")
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
            Button("API 价格表（本机估算）…") { PricesWindow.show() }
            Button("预算与异常提醒…") { BudgetWindow.show() }
            Button("数据状态与省资源…") { DataStatusWindow.show() }
            Toggle("读取 Claude 额度", isOn: Binding(get: { store.claudeEnabled }, set: { store.claudeEnabled = $0 }))
            Toggle("全员重置预测（联网读第三方追踪站）", isOn: Binding(get: { store.forecastEnabled }, set: { store.forecastEnabled = $0 }))
            Toggle("自动领取每日积分（TRAE 签到 · WorkBuddy 任务奖励）",
                   isOn: Binding(get: { store.autoClaimEnabled }, set: { store.autoClaimEnabled = $0 }))
            Picker("每日领取时间（北京时间）", selection: Binding(get: { store.claimTime }, set: { store.claimTime = $0 })) {
                ForEach(UsageStore.claimTimeOptions, id: \.self) { Text($0).tag($0) }
            }
            .disabled(!store.autoClaimEnabled)
            Divider()
            Toggle("额度与到期提醒", isOn: Binding(get: { store.notificationsEnabled }, set: { store.notificationsEnabled = $0 }))
            Picker("额度不足阈值", selection: Binding(get: { store.lowQuotaThreshold }, set: { store.lowQuotaThreshold = $0 })) {
                ForEach([10.0, 20.0, 30.0], id: \.self) { Text("剩余 ≤ \(Int($0))%").tag($0) }
            }
            .disabled(!store.notificationsEnabled)
            Button("发送测试通知") { Notifier.shared.sendTest() }
            Divider()
            Menu("桌宠") {
                let pet = PetPrefs.shared
                Toggle("显示桌宠", isOn: Binding(get: { pet.enabled }, set: { pet.enabled = $0 }))
                Picker("形象", selection: Binding(get: { pet.packID }, set: { pet.packID = $0 })) {
                    ForEach(PetResources.allPacks()) { Text($0.name).tag($0.id) }
                }
                Picker("大小", selection: Binding(get: { pet.size }, set: { pet.size = $0 })) {
                    ForEach(PetSize.allCases) { Text($0.label).tag($0) }
                }
                Picker("额度显示", selection: Binding(get: { pet.hud }, set: { pet.hud = $0 })) {
                    ForEach(PetHUD.allCases) { Text($0.label).tag($0) }
                }
                Toggle("眼睛跟随光标", isOn: Binding(get: { pet.followCursor }, set: { pet.followCursor = $0 }))
                Toggle("安静模式（少说话、不乱动）", isOn: Binding(get: { pet.calm }, set: { pet.calm = $0 }))
                Toggle("用桌宠气泡代替系统通知", isOn: Binding(get: { pet.takeoverAlerts }, set: { pet.takeoverAlerts = $0 }))
                Picker("久坐提醒", selection: Binding(get: { pet.breakMinutes }, set: { pet.breakMinutes = $0 })) {
                    Text("关闭").tag(0)
                    Text("连续 1 小时").tag(60)
                    Text("连续 2 小时").tag(120)
                    Text("连续 3 小时").tag(180)
                }
                Divider()
                Button("打开桌宠页") { tabRaw = Tab.pet.rawValue }
                Button("打开形象文件夹…") { PetController.shared.openUserFolder() }
            }
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
            switch selectedTab {
            case .accounts: AccountsView(snapshot: snapshot, now: store.now)
            case .forecast: ForecastView(snapshot: snapshot, now: store.now)
            case .usage: UsageView(snapshot: snapshot, now: store.now, budget: store.budget)
            case .apps: ActivityView(snapshot: snapshot)
            case .pet: PetTabView()
            case .collection: CollectionView(snapshot: snapshot, now: store.now)
            }
        }
        .padding(14)
    }

    /// The pet works without a snapshot (it simply looks "not sure"), so its tab never waits for one.
    @ViewBuilder private var petContent: some View {
        if Self.expandForPreview {
            PetTabView().padding(14)
        } else {
            ScrollView { PetTabView().padding(14) }.scrollIndicators(.never).frame(height: 480)
        }
    }

    @ViewBuilder private var content: some View {
        if selectedTab == .pet {
            petContent
        } else if let snapshot = store.snapshot {
            if Self.expandForPreview {
                tabContent(snapshot)
            } else {
                ScrollView { tabContent(snapshot) }.scrollIndicators(.never).frame(height: 480)
            }
        } else if let error = store.errorMessage {
            VStack(spacing: 12) {
                Image(systemName: "bolt.horizontal.circle").font(.system(size: 34)).foregroundStyle(.orange)
                Text("无法读取用量").font(.system(size: 14, weight: .semibold))
                Text(error).font(.system(size: 11.5)).themeForeground(.secondary).multilineTextAlignment(.center)
                Button("重试") { store.refresh() }.controlSize(.regular)
            }
            .padding(28)
            .frame(maxWidth: .infinity)
            .frame(height: 300)
        } else {
            VStack(spacing: 12) {
                ProgressView().controlSize(.regular)
                Text(store.phase == .starting ? "正在启动本机后端…" : "正在读取账户额度与本机记录…")
                    .font(.system(size: 12)).themeForeground(.secondary)
                Text("首次采集通常需要几秒").font(.system(size: 10.5)).themeForeground(.tertiary)
            }
            .frame(maxWidth: .infinity)
            .frame(height: 300)
        }
    }

    // MARK: Footer

    private var footer: some View {
        VStack(alignment: .leading, spacing: 3) {
        HStack(spacing: 6) {
            if let s = store.snapshot {
                let summary = s.summary
                Image(systemName: "square.stack.3d.up").font(.system(size: 10))
                Text("\(Int(summary["application_groups"].double ?? summary["applications"].double ?? 0)) 个应用 · \(Int(summary["available_fields"].double ?? 0)) 项已采集 · \(Int(summary["partial_fields"].double ?? 0)) 项部分")
            } else {
                // String(), not interpolation: a number inside Text("...") gets a locale thousands separator ("8,769").
                Text("本机只读 · 127.0.0.1:" + String(BackendClient.port))
            }
            Spacer()
            Text("北京时间")
        }
        Text(Fmt.currencyNote).font(.system(size: 9))
        }
        .font(.system(size: 10.5))
        .themeForeground(.secondary)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }
}

/// App mark next to the title; grows louder with the theme.
private struct HeaderLogo: View {
    @Environment(\.panelTheme) private var theme

    var body: some View {
        switch theme {
        case .minimal:
            EmptyView()
        case .native:
            BrandMark(outer: Color.white, inner: Color.white, trackOpacity: 0.3)
                .frame(width: 28, height: 28)
                .background(RoundedRectangle(cornerRadius: 7, style: .continuous).fill(Color.accentColor))
        case .porcelain, .aurora, .titanium:
            BrandMark(outer: Color.white, inner: Brand.mint)
                .frame(width: 32, height: 32)
                .background(RoundedRectangle(cornerRadius: 7.2, style: .continuous).fill(Brand.plate))
                .shadow(color: Color(red: 0.55, green: 0.4, blue: 1).opacity(0.8), radius: 8)
        case .neon, .prism:
            ZStack {
                Hexagon().fill(Color.black.opacity(0.6))
                Hexagon().stroke(Neon.rim, lineWidth: 1.5)
                BrandMark(outer: Neon.magenta, inner: Neon.cyan, sparkle: Neon.cyan, trackOpacity: 0.25)
                    .frame(width: 22, height: 22)
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
        case .porcelain, .aurora, .titanium:
            Text("Agent 用量").font(.system(size: 15, weight: .heavy, design: .rounded))
                .foregroundStyle(LinearGradient(colors: [.primary, Color(red: 0.6, green: 0.5, blue: 1)], startPoint: .leading, endPoint: .trailing))
        case .neon, .prism:
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
            let a: CGFloat = CGFloat(i) * .pi / 3 - .pi / 2
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
            Text("刷新失败，显示上次数据。\(message)").font(.system(size: 11)).themeForeground(.secondary)
            Spacer(minLength: 0)
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Color.orange.opacity(0.1)))
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
                .font(.system(size: 9)).themeForeground(.secondary).monospacedDigit()
        }
        .frame(minWidth: 52)
    }
}
